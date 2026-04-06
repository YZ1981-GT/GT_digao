export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  knowledgeRefs?: string[];
  attachments?: ChatAttachment[];
  moduleRecommendation?: string;
  savedToNotes?: boolean;
  suggestSaveNote?: boolean;
}

export interface ChatAttachment {
  filename: string;
  size: number;
  type: 'document' | 'image';
  content?: string;
  thumbnailUrl?: string;
}

export interface ChatSession {
  id: string;
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeRef {
  libraryId: string;
  libraryName: string;
}

export interface QuickCommand {
  command: string;
  label: string;
  mode: 'review' | 'generate' | 'analysis' | 'report_review';
  icon: string;
}

export const QUICK_COMMANDS: QuickCommand[] = [
  { command: '/复核', label: '底稿复核', mode: 'review', icon: '📋' },
  { command: '/生成', label: '文档生成', mode: 'generate', icon: '📝' },
  { command: '/分析', label: '文档分析', mode: 'analysis', icon: '🔍' },
  { command: '/报告复核', label: '审计报告复核', mode: 'report_review', icon: '📊' },
];

export interface NoteItem {
  id: string;
  title: string;
  createdAt: string;
  size: number;
}

export interface NoteGroup {
  date: string;
  notes: NoteItem[];
}
