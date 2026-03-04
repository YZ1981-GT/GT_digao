/**
 * 本地草稿持久化（IndexedDB + localStorage 降级）
 *
 * 使用 IndexedDB 存储大容量正文内容，localStorage 存储轻量元数据。
 * 如果 IndexedDB 不可用，自动降级到 localStorage。
 */

import type { AppState, OutlineItem } from '../types';

const DRAFT_KEY = 'gt:draft:v1';
const CONTENT_BY_ID_KEY = 'gt:contentById:v1';
const DB_NAME = 'gt-bidwriter';
const DB_VERSION = 1;
const STORE_NAME = 'drafts';

export type DraftState = Pick<
  AppState,
  'currentStep' | 'fileContent' | 'projectOverview' | 'techRequirements' | 'outlineData' | 'selectedChapter'
>;

export type ContentById = Record<string, string>;

/* ========== IndexedDB 工具 ========== */

let dbInstance: IDBDatabase | null = null;
let dbFailed = false; // 标记 IndexedDB 是否不可用

function openDB(): Promise<IDBDatabase> {
  if (dbInstance) return Promise.resolve(dbInstance);
  if (dbFailed) return Promise.reject(new Error('IndexedDB unavailable'));

  return new Promise((resolve, reject) => {
    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME);
        }
      };
      request.onsuccess = () => {
        dbInstance = request.result;
        resolve(dbInstance);
      };
      request.onerror = () => {
        dbFailed = true;
        reject(request.error);
      };
    } catch {
      dbFailed = true;
      reject(new Error('IndexedDB not supported'));
    }
  });
}

async function idbGet<T>(key: string): Promise<T | null> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const req = tx.objectStore(STORE_NAME).get(key);
    req.onsuccess = () => resolve(req.result ?? null);
    req.onerror = () => reject(req.error);
  });
}

async function idbSet(key: string, value: unknown): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function idbClear(): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).clear();
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/* ========== localStorage 降级工具 ========== */

const safeJsonParse = <T,>(raw: string | null): T | null => {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
};

/* ========== 同步 API（元数据，体积小，用 localStorage） ========== */

function loadDraftSync(): Partial<DraftState> | null {
  return safeJsonParse<Partial<DraftState>>(localStorage.getItem(DRAFT_KEY));
}

function saveDraftSync(partial: Partial<DraftState>) {
  try {
    const prev = safeJsonParse<Partial<DraftState>>(localStorage.getItem(DRAFT_KEY)) || {};
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...prev, ...partial }));
  } catch (e) {
    console.warn('保存草稿失败:', e);
  }
}

/* ========== 异步 API（正文内容，体积大，优先 IndexedDB） ========== */

async function loadContentByIdAsync(): Promise<ContentById> {
  try {
    const data = await idbGet<ContentById>(CONTENT_BY_ID_KEY);
    if (data) return data;
  } catch {
    // IndexedDB 不可用，降级
  }
  return safeJsonParse<ContentById>(localStorage.getItem(CONTENT_BY_ID_KEY)) || {};
}

async function saveContentByIdAsync(contentById: ContentById): Promise<void> {
  try {
    await idbSet(CONTENT_BY_ID_KEY, contentById);
    // 同时清理 localStorage 中的旧数据（如果有）
    try { localStorage.removeItem(CONTENT_BY_ID_KEY); } catch { /* ignore */ }
    return;
  } catch {
    // IndexedDB 不可用，降级到 localStorage
  }
  try {
    localStorage.setItem(CONTENT_BY_ID_KEY, JSON.stringify(contentById));
  } catch (e) {
    console.warn('保存正文内容失败（可能是存储空间不足）:', e);
  }
}

/* ========== 对外导出的 draftStorage ========== */

export const draftStorage = {
  /** 同步加载元数据草稿（用于初始化state） */
  loadDraft(): Partial<DraftState> | null {
    return loadDraftSync();
  },

  /** 同步保存元数据草稿 */
  saveDraft(partial: Partial<DraftState>) {
    saveDraftSync(partial);
  },

  /** 清空所有存储（上传新文件时调用） */
  clearAll() {
    try { localStorage.clear(); } catch { /* ignore */ }
    idbClear().catch(() => { /* ignore */ });
  },

  /** 同步加载正文（兼容旧版，优先从 localStorage 读取） */
  loadContentById(): ContentById {
    return safeJsonParse<ContentById>(localStorage.getItem(CONTENT_BY_ID_KEY)) || {};
  },

  /** 异步加载正文（优先 IndexedDB） */
  loadContentByIdAsync(): Promise<ContentById> {
    return loadContentByIdAsync();
  },

  /** 同步保存正文（兼容旧版调用） */
  saveContentById(contentById: ContentById) {
    // 异步写入 IndexedDB，同时同步写入 localStorage 作为即时可读备份
    saveContentByIdAsync(contentById).catch(() => { /* ignore */ });
    try {
      localStorage.setItem(CONTENT_BY_ID_KEY, JSON.stringify(contentById));
    } catch { /* ignore */ }
  },

  /** 更新单个章节内容 */
  upsertChapterContent(chapterId: string, content: string) {
    try {
      const map = this.loadContentById();
      map[chapterId] = content;
      this.saveContentById(map);
    } catch (e) {
      console.warn('保存章节内容失败:', e);
    }
  },

  /**
   * 按当前 outline 的叶子节点过滤 contentById，避免目录变更后错误回填。
   */
  filterContentByOutlineLeaves(outline: OutlineItem[]): ContentById {
    const map = this.loadContentById();
    const leafIds = new Set<string>();
    const walk = (items: OutlineItem[]) => {
      items.forEach((it) => {
        if (!it.children || it.children.length === 0) {
          leafIds.add(it.id);
        } else {
          walk(it.children);
        }
      });
    };
    walk(outline);

    const filtered: ContentById = {};
    Object.keys(map).forEach((id) => {
      if (leafIds.has(id)) filtered[id] = map[id];
    });
    return filtered;
  },
};
