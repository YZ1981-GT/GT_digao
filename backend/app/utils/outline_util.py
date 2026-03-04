import random
from typing import Dict, List, Tuple


def get_random_indexes(max_index: int) -> Tuple[int, int]:
    """
    从0到max_index范围内随机选择两个不同的索引
    
    Args:
        max_index: 索引的最大值（不包含）
        
    Returns:
        Tuple[int, int]: 两个不同的随机索引
    """
    if max_index <= 1:
        return (0, 0)
    
    i, j = random.sample(range(max_index), 2)
    return (i, j)


def calculate_nodes_distribution_by_weights(
    weights: List[float],
    total_leaf_nodes: int,
) -> dict:
    """
    根据权重列表按比例分配叶子节点和二级节点。

    Args:
        weights: 每个一级节点的权重（如评分分值），长度 = 一级节点数量。
                 权重为 0 的节点会被赋予最小权重以保证至少分配 1 个叶子。
        total_leaf_nodes: 需要的叶子节点总数

    Returns:
        dict: 与 calculate_nodes_distribution 相同的格式
        {
            'level2_nodes': [...],
            'leaf_nodes': [...],
            'leaf_per_level2': [[...], ...]
        }
    """
    n = len(weights)
    if n == 0:
        return {'level2_nodes': [], 'leaf_nodes': [], 'leaf_per_level2': []}

    # 保证每个节点至少有最小权重
    safe_weights = [max(w, 0.1) for w in weights]
    total_weight = sum(safe_weights)

    # 保证 total_leaf_nodes 至少等于节点数（每个至少 1 个叶子）
    total_leaf_nodes = max(total_leaf_nodes, n)

    # --- 按权重比例分配叶子节点（保证总和精确等于 total_leaf_nodes） ---
    # 先按比例计算浮点值，再用最大余数法取整
    raw = [total_leaf_nodes * w / total_weight for w in safe_weights]
    leaf_nodes = [max(int(r), 1) for r in raw]  # 每个至少 1

    # 计算已分配和剩余
    allocated = sum(leaf_nodes)
    remaining = total_leaf_nodes - allocated

    if remaining > 0:
        # 按小数部分从大到小分配剩余
        fractions = [(raw[i] - leaf_nodes[i], i) for i in range(n)]
        fractions.sort(key=lambda x: -x[0])
        for j in range(min(remaining, n)):
            leaf_nodes[fractions[j][1]] += 1
    elif remaining < 0:
        # 分配过多（因为 max(...,1) 保底），从最大的节点中扣减
        over = -remaining
        indexed = sorted(range(n), key=lambda i: -leaf_nodes[i])
        for j in range(n):
            if over <= 0:
                break
            idx = indexed[j]
            can_reduce = leaf_nodes[idx] - 1  # 至少保留 1
            reduce = min(can_reduce, over)
            leaf_nodes[idx] -= reduce
            over -= reduce

    # --- 按叶子数推算二级节点数 ---
    # 每个二级下的叶子数在 2~9 之间变化，避免千篇一律的"每级3个"
    level2_nodes = []
    for lf in leaf_nodes:
        if lf <= 2:
            level2_nodes.append(1)
        elif lf <= 9:
            level2_nodes.append(random.choice([1, 2]))
        else:
            # 随机选择每个二级下平均 2~9 个叶子
            avg_per_l2 = random.choice([2, 3, 4, 5, 6, 7, 8, 9])
            l2 = max(round(lf / avg_per_l2), 2)
            level2_nodes.append(l2)

    # --- 将叶子不均匀分配到二级节点（模拟真实目录的参差感） ---
    leaf_per_level2: List[List[int]] = []
    for i in range(n):
        l2_count = level2_nodes[i]
        lf_count = leaf_nodes[i]
        if l2_count == 1:
            leaf_per_level2.append([lf_count])
        else:
            # 先均匀分配，再随机微调
            base = lf_count // l2_count
            extra = lf_count % l2_count
            dist = [(base + 1) if j < extra else base for j in range(l2_count)]
            # 随机交换一些叶子，让分布不均匀（但保持总数不变）
            for _ in range(l2_count):
                a, b = random.sample(range(l2_count), 2)
                if dist[a] > 1:  # 确保不会减到0
                    transfer = random.randint(0, min(dist[a] - 1, 2))
                    dist[a] -= transfer
                    dist[b] += transfer
            leaf_per_level2.append(dist)

    return {
        'level2_nodes': level2_nodes,
        'leaf_nodes': leaf_nodes,
        'leaf_per_level2': leaf_per_level2,
    }


def calculate_nodes_distribution(level1_count: int, important_indexes: tuple[int, int], total_leaf_nodes: int) -> dict:
    """
    计算树结构中各节点的分配数量（均匀分配 + 重要节点加权）。
    商务部分等无分值场景使用此函数。

    Args:
        level1_count: 一级节点数量
        important_indexes: 两个重要节点的索引（从0开始）
        total_leaf_nodes: 需要的叶子节点总数

    Returns:
        dict: 包含节点分配信息的字典
    """
    # 构造权重列表：重要节点加权
    primary_weight = 1.4
    secondary_weight = 1.2
    normal_weight = 1.0

    weights = [normal_weight] * level1_count
    weights[important_indexes[0]] = primary_weight
    if important_indexes[1] != important_indexes[0]:
        weights[important_indexes[1]] = secondary_weight

    return calculate_nodes_distribution_by_weights(weights, total_leaf_nodes)

def generate_one_outline_json_by_level1(level1_title: str, level1_index: int, nodes_distribution: Dict, words_per_leaf: int = 1500) -> Dict:
    """
    根据一级标题生成该标题下的完整大纲结构
    
    Args:
        level1_title: 一级标题
        level1_index: 一级标题的索引（从1开始）
        nodes_distribution: 节点分配信息，包含 level2_nodes 和 leaf_per_level2
        words_per_leaf: 每个叶子节点的目标字数
        
    Returns:
        Dict: 一级标题的完整大纲结构
    """
    # 获取当前一级节点下的二级节点数量和叶子节点分配
    level2_count = nodes_distribution['level2_nodes'][level1_index - 1]
    leaf_distribution = nodes_distribution['leaf_per_level2'][level1_index - 1]
    
    # 计算一级节点的总字数
    total_leaves = sum(leaf_distribution)
    level1_word_count = total_leaves * words_per_leaf
    
    # 创建一级节点
    level1_node = {
        "id":f"{level1_index}",
        "title": level1_title,
        "description": "",
        "target_word_count": level1_word_count,
        "children": []
    }
    
    # 创建二级节点
    for j in range(level2_count):
        leaf_count = leaf_distribution[j]
        level2_word_count = leaf_count * words_per_leaf
        
        level2_node = {
            "id":f"{level1_index}.{j+1}",
            "title": "",  # 二级标题留空
            "description": "",
            "target_word_count": level2_word_count,
            "children": []
        }
        
        # 创建三级节点（叶子节点）
        for k in range(leaf_count):
            level2_node["children"].append({
                "id":f"{level1_index}.{j+1}.{k+1}",
                "title": "",  # 三级标题留空
                "description": "",
                "target_word_count": words_per_leaf
            })
        
        level1_node["children"].append(level2_node)
    
    return level1_node