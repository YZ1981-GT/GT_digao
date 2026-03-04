/**
 * 审计工作状态 IndexedDB 缓存
 *
 * 使用 IndexedDB 存储审计复核工作流的完整状态，
 * 包括已上传底稿列表、复核配置、所选提示词、补充材料和复核报告。
 * 页面刷新或重新打开浏览器后可恢复上次的工作状态。
 *
 * 遵循现有 draftStorage.ts 的 IndexedDB 使用模式。
 */

import type {
  WorkpaperParseResult,
  ReviewPromptInfo,
  SupplementaryMaterial,
  ReviewReport,
  ReviewDimension,
} from '../types/audit';

const DB_NAME = 'audit-workpaper-review';
const DB_VERSION = 1;
const STORE_NAME = 'state';
const STATE_KEY = 'audit:state:v1';

/** 复核配置 */
export interface ReviewConfig {
  dimensions: ReviewDimension[];
  customDimensions: string[];
  promptId: string | null;
  customPrompt: string | null;
}

/** 审计工作状态 */
export interface AuditWorkState {
  uploadedWorkpapers: WorkpaperParseResult[];
  reviewConfig: ReviewConfig;
  selectedPrompt: ReviewPromptInfo | null;
  supplementaryMaterials: SupplementaryMaterial[];
  reviewReport: ReviewReport | null;
}

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

/* ========== 公共 API ========== */

/**
 * 保存审计工作状态到 IndexedDB。
 * 处理 QuotaExceededError：存储空间不足时记录警告但不抛出异常。
 */
export async function saveAuditState(state: AuditWorkState): Promise<void> {
  try {
    await idbSet(STATE_KEY, state);
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'QuotaExceededError') {
      console.warn('审计工作状态保存失败：浏览器存储空间不足', e);
      return;
    }
    console.warn('审计工作状态保存失败:', e);
  }
}

/**
 * 从 IndexedDB 加载审计工作状态。
 * 若无缓存数据则返回 null。
 */
export async function loadAuditState(): Promise<AuditWorkState | null> {
  try {
    return await idbGet<AuditWorkState>(STATE_KEY);
  } catch {
    console.warn('审计工作状态加载失败，返回 null');
    return null;
  }
}

/**
 * 清空审计工作状态缓存。
 */
export async function clearAuditState(): Promise<void> {
  try {
    await idbClear();
  } catch {
    console.warn('审计工作状态清除失败');
  }
}
