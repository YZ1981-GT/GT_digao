/**
 * 聊天会话 IndexedDB 持久化
 *
 * 使用 IndexedDB 存储聊天会话数据，包含两个 object store：
 *   - chat_current：当前活跃会话（仅一条记录，key='current'）
 *   - chat_archive：归档会话列表（key=session.id）
 *
 * 页面刷新或重新打开浏览器后可恢复上次的对话状态。
 * 复用 auditStorage 的 IndexedDB 使用模式。
 */

import type { ChatSession } from '../types/chat';

const DB_NAME = 'gt_chat_db';
const DB_VERSION = 1;
const STORE_CURRENT = 'chat_current';
const STORE_ARCHIVE = 'chat_archive';
const CURRENT_KEY = 'current';

/* ========== IndexedDB 工具 ========== */

let dbInstance: IDBDatabase | null = null;
let dbFailed = false;

function openDB(): Promise<IDBDatabase> {
  if (dbInstance) return Promise.resolve(dbInstance);
  if (dbFailed) return Promise.reject(new Error('IndexedDB unavailable'));

  return new Promise((resolve, reject) => {
    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_CURRENT)) {
          db.createObjectStore(STORE_CURRENT);
        }
        if (!db.objectStoreNames.contains(STORE_ARCHIVE)) {
          db.createObjectStore(STORE_ARCHIVE);
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

/* ========== 公共 API ========== */

/**
 * 保存当前聊天会话到 chat_current store。
 * 处理 QuotaExceededError：存储空间不足时记录警告但不抛出异常。
 */
export async function saveChatSession(session: ChatSession): Promise<void> {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_CURRENT, 'readwrite');
      tx.objectStore(STORE_CURRENT).put(session, CURRENT_KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'QuotaExceededError') {
      console.warn('聊天会话保存失败：浏览器存储空间不足', e);
      return;
    }
    console.warn('聊天会话保存失败:', e);
  }
}

/**
 * 从 chat_current store 加载当前聊天会话。
 * 若无缓存数据或读取失败则返回 null，不阻塞聊天功能。
 */
export async function loadChatSession(): Promise<ChatSession | null> {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_CURRENT, 'readonly');
      const req = tx.objectStore(STORE_CURRENT).get(CURRENT_KEY);
      req.onsuccess = () => resolve(req.result ?? null);
      req.onerror = () => reject(req.error);
    });
  } catch {
    console.warn('聊天会话加载失败，返回 null');
    return null;
  }
}

/**
 * 归档当前会话：将 session 写入 chat_archive store，然后清空 chat_current store。
 * 用于"新建对话"时保存旧会话。
 */
export async function archiveChatSession(session: ChatSession): Promise<void> {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction([STORE_ARCHIVE, STORE_CURRENT], 'readwrite');
      tx.objectStore(STORE_ARCHIVE).put(session, session.id);
      tx.objectStore(STORE_CURRENT).delete(CURRENT_KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'QuotaExceededError') {
      console.warn('聊天会话归档失败：浏览器存储空间不足', e);
      return;
    }
    console.warn('聊天会话归档失败:', e);
  }
}
