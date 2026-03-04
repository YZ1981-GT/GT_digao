/**
 * ProjectPanel - 项目管理面板
 *
 * 两个视图：ProjectList（项目列表）和 ProjectDetail（项目详情）。
 * 支持创建项目、关联底稿、关联模板、按业务循环筛选底稿、复核进度概览。
 *
 * Requirements: 5.1-5.7, 11.7
 */
import React, { useState, useEffect, useCallback } from 'react';
import type {
  ProjectDetail,
  ProjectCreateRequest,
  ProjectReviewSummary,
  UserRole,
} from '../types/audit';
import { projectApi } from '../services/api';
import '../styles/gt-design-tokens.css';

/** Business cycle options for workpaper filtering */
const BUSINESS_CYCLES: Array<{ value: string; label: string }> = [
  { value: '', label: '全部业务循环' },
  { value: 'D', label: '销售循环' },
  { value: 'E', label: '货币资金循环' },
  { value: 'F', label: '存货循环' },
  { value: 'G', label: '投资循环' },
  { value: 'H', label: '固定资产循环' },
  { value: 'I', label: '无形资产循环' },
  { value: 'J', label: '职工薪酬循环' },
  { value: 'K', label: '管理循环' },
  { value: 'L', label: '债务循环' },
  { value: 'M', label: '权益循环' },
  { value: 'Q', label: '关联方循环' },
];

/** Role display labels */
const ROLE_LABELS: Record<UserRole, string> = {
  partner: '合伙人',
  manager: '项目经理',
  auditor: '审计员',
  qc: '质控人员',
};

/** Workpaper info returned from filter API */
interface WorkpaperInfo {
  id: string;
  filename: string;
  workpaper_type?: string;
  business_cycle?: string;
  parse_status: string;
}

// ─── Create Project Form ───

interface CreateProjectFormProps {
  onSubmit: (data: ProjectCreateRequest) => void;
  onCancel: () => void;
  isSubmitting: boolean;
}

const CreateProjectForm: React.FC<CreateProjectFormProps> = ({ onSubmit, onCancel, isSubmitting }) => {
  const [name, setName] = useState('');
  const [clientName, setClientName] = useState('');
  const [auditPeriod, setAuditPeriod] = useState('');
  const [members, setMembers] = useState<Array<{ user_id: string; role: string }>>([
    { user_id: '', role: 'auditor' },
  ]);

  const handleAddMember = () => {
    setMembers((prev) => [...prev, { user_id: '', role: 'auditor' }]);
  };

  const handleRemoveMember = (index: number) => {
    setMembers((prev) => prev.filter((_, i) => i !== index));
  };

  const handleMemberChange = (index: number, field: 'user_id' | 'role', value: string) => {
    setMembers((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !clientName.trim() || !auditPeriod.trim()) return;
    const validMembers = members.filter((m) => m.user_id.trim());
    onSubmit({ name: name.trim(), client_name: clientName.trim(), audit_period: auditPeriod.trim(), members: validMembers });
  };

  return (
    <form onSubmit={handleSubmit} aria-label="创建审计项目">
      <div className="gt-card">
        <div className="gt-card-header">
          <h3 className="gt-h4" style={{ margin: 0, color: 'var(--gt-primary)' }}>创建审计项目</h3>
        </div>
        <div className="gt-card-content" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-4)' }}>
          {/* Project name */}
          <div>
            <label htmlFor="project-name" style={{ display: 'block', fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-1)' }}>
              项目名称 <span style={{ color: 'var(--gt-danger)' }}>*</span>
            </label>
            <input
              id="project-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="请输入项目名称"
              style={{ width: '100%', padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-sm)', border: '1px solid #d0d0d0', fontSize: 'var(--gt-font-sm)', boxSizing: 'border-box' }}
            />
          </div>

          {/* Client name */}
          <div>
            <label htmlFor="client-name" style={{ display: 'block', fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-1)' }}>
              客户名称 <span style={{ color: 'var(--gt-danger)' }}>*</span>
            </label>
            <input
              id="client-name"
              type="text"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              required
              placeholder="请输入客户名称"
              style={{ width: '100%', padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-sm)', border: '1px solid #d0d0d0', fontSize: 'var(--gt-font-sm)', boxSizing: 'border-box' }}
            />
          </div>

          {/* Audit period */}
          <div>
            <label htmlFor="audit-period" style={{ display: 'block', fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-1)' }}>
              审计期间 <span style={{ color: 'var(--gt-danger)' }}>*</span>
            </label>
            <input
              id="audit-period"
              type="text"
              value={auditPeriod}
              onChange={(e) => setAuditPeriod(e.target.value)}
              required
              placeholder="例如：2024年1月1日 - 2024年12月31日"
              style={{ width: '100%', padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-sm)', border: '1px solid #d0d0d0', fontSize: 'var(--gt-font-sm)', boxSizing: 'border-box' }}
            />
          </div>

          {/* Members */}
          <fieldset style={{ border: 'none', padding: 0, margin: 0 }}>
            <legend style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-2)' }}>
              项目组成员
            </legend>
            {members.map((member, idx) => (
              <div key={idx} style={{ display: 'flex', gap: 'var(--gt-space-2)', marginBottom: 'var(--gt-space-2)', alignItems: 'center' }}>
                <input
                  type="text"
                  value={member.user_id}
                  onChange={(e) => handleMemberChange(idx, 'user_id', e.target.value)}
                  placeholder="用户ID"
                  aria-label={`成员 ${idx + 1} 用户ID`}
                  style={{ flex: 1, padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-sm)', border: '1px solid #d0d0d0', fontSize: 'var(--gt-font-sm)' }}
                />
                <select
                  value={member.role}
                  onChange={(e) => handleMemberChange(idx, 'role', e.target.value)}
                  aria-label={`成员 ${idx + 1} 角色`}
                  style={{ padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-sm)', border: '1px solid #d0d0d0', fontSize: 'var(--gt-font-sm)' }}
                >
                  <option value="partner">合伙人</option>
                  <option value="manager">项目经理</option>
                  <option value="auditor">审计员</option>
                  <option value="qc">质控人员</option>
                </select>
                {members.length > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveMember(idx)}
                    aria-label={`移除成员 ${idx + 1}`}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--gt-danger)', fontSize: 'var(--gt-font-base)', padding: 'var(--gt-space-1)' }}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              className="gt-button gt-button--secondary"
              onClick={handleAddMember}
              style={{ fontSize: 'var(--gt-font-sm)' }}
            >
              + 添加成员
            </button>
          </fieldset>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 'var(--gt-space-3)', justifyContent: 'flex-end', marginTop: 'var(--gt-space-2)' }}>
            <button type="button" className="gt-button gt-button--secondary" onClick={onCancel} disabled={isSubmitting}>
              取消
            </button>
            <button type="submit" className="gt-button gt-button--primary" disabled={isSubmitting || !name.trim() || !clientName.trim() || !auditPeriod.trim()}>
              {isSubmitting ? '创建中...' : '创建项目'}
            </button>
          </div>
        </div>
      </div>
    </form>
  );
};

// ─── Review Summary ───

interface ReviewSummaryProps {
  summary: ProjectReviewSummary;
}

const ReviewSummarySection: React.FC<ReviewSummaryProps> = ({ summary }) => {
  const { total_workpapers, reviewed_workpapers, pending_workpapers, high_risk_count, medium_risk_count, low_risk_count } = summary;
  const pct = total_workpapers > 0 ? Math.round((reviewed_workpapers / total_workpapers) * 100) : 0;

  return (
    <section aria-labelledby="review-summary-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
      <div className="gt-card">
        <div className="gt-card-header">
          <h4 id="review-summary-heading" className="gt-h4" style={{ margin: 0, color: 'var(--gt-primary)' }}>复核进度概览</h4>
        </div>
        <div className="gt-card-content">
          {/* Progress bar */}
          <div style={{ marginBottom: 'var(--gt-space-4)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', marginBottom: 'var(--gt-space-1)' }}>
              <span>已复核 {reviewed_workpapers} / 待复核 {pending_workpapers}</span>
              <span>{pct}%</span>
            </div>
            <div
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`复核进度 ${pct}%`}
              style={{ width: '100%', height: 8, backgroundColor: '#e8e8e8', borderRadius: 'var(--gt-radius-sm)', overflow: 'hidden' }}
            >
              <div style={{ width: `${pct}%`, height: '100%', backgroundColor: 'var(--gt-primary)', borderRadius: 'var(--gt-radius-sm)', transition: 'width 0.3s ease' }} />
            </div>
          </div>

          {/* Risk counts */}
          <div style={{ display: 'flex', gap: 'var(--gt-space-4)', flexWrap: 'wrap' }}>
            <span className="gt-risk-badge gt-risk-badge--high">
              <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: 'var(--gt-danger)', display: 'inline-block' }} />
              高风险：{high_risk_count}
            </span>
            <span className="gt-risk-badge gt-risk-badge--medium">
              <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: 'var(--gt-warning)', display: 'inline-block' }} />
              中风险：{medium_risk_count}
            </span>
            <span className="gt-risk-badge gt-risk-badge--low">
              <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: 'var(--gt-info)', display: 'inline-block' }} />
              低风险：{low_risk_count}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
};

// ─── Project Detail View ───

interface ProjectDetailViewProps {
  project: ProjectDetail;
  onBack: () => void;
}

const ProjectDetailView: React.FC<ProjectDetailViewProps> = ({ project, onBack }) => {
  const [summary, setSummary] = useState<ProjectReviewSummary | null>(null);
  const [workpapers, setWorkpapers] = useState<WorkpaperInfo[]>([]);
  const [cycleFilter, setCycleFilter] = useState('');
  const [linkWorkpaperId, setLinkWorkpaperId] = useState('');
  const [linkTemplateId, setLinkTemplateId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    try {
      const res = await projectApi.getProjectSummary(project.id);
      setSummary(res.data);
    } catch {
      /* summary may not be available yet */
    }
  }, [project.id]);

  const loadWorkpapers = useCallback(async (cycle?: string) => {
    try {
      const params = cycle ? { cycle } : undefined;
      const res = await projectApi.filterWorkpapers(project.id, params);
      setWorkpapers(res.data as WorkpaperInfo[]);
    } catch {
      setWorkpapers([]);
    }
  }, [project.id]);

  useEffect(() => {
    loadSummary();
    loadWorkpapers();
  }, [loadSummary, loadWorkpapers]);

  const handleCycleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    setCycleFilter(val);
    loadWorkpapers(val || undefined);
  };

  const handleLinkWorkpaper = async () => {
    if (!linkWorkpaperId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await projectApi.addWorkpaperToProject(project.id, { workpaper_id: linkWorkpaperId.trim() });
      setLinkWorkpaperId('');
      loadWorkpapers(cycleFilter || undefined);
      loadSummary();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '关联底稿失败');
    } finally {
      setLoading(false);
    }
  };

  const handleLinkTemplate = async () => {
    if (!linkTemplateId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await projectApi.linkTemplateToProject(project.id, { template_id: linkTemplateId.trim() });
      setLinkTemplateId('');
    } catch (err: any) {
      setError(err?.response?.data?.detail || '关联模板失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      {/* Back button + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-5)' }}>
        <button className="gt-button gt-button--secondary" onClick={onBack} aria-label="返回项目列表">
          ← 返回
        </button>
        <h2 className="gt-h3" style={{ margin: 0, color: 'var(--gt-text-primary)' }}>{project.name}</h2>
      </div>

      {error && (
        <div role="alert" style={{ padding: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-4)', backgroundColor: 'rgba(220,53,69,0.08)', borderRadius: 'var(--gt-radius-sm)', color: 'var(--gt-danger)', fontSize: 'var(--gt-font-sm)' }}>
          {error}
        </div>
      )}

      {/* Project info card */}
      <section aria-labelledby="project-info-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
        <div className="gt-card">
          <div className="gt-card-header">
            <h3 id="project-info-heading" className="gt-h4" style={{ margin: 0, color: 'var(--gt-primary)' }}>项目信息</h3>
          </div>
          <div className="gt-card-content">
            <div className="gt-grid gt-grid-2" style={{ gap: 'var(--gt-space-4)' }}>
              <div>
                <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>客户名称</span>
                <p style={{ margin: '4px 0 0', fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-primary)', fontWeight: 600 }}>{project.client_name}</p>
              </div>
              <div>
                <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>审计期间</span>
                <p style={{ margin: '4px 0 0', fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-primary)', fontWeight: 600 }}>{project.audit_period}</p>
              </div>
              <div>
                <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>项目状态</span>
                <p style={{ margin: '4px 0 0', fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-primary)', fontWeight: 600 }}>{project.status}</p>
              </div>
              <div>
                <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>底稿数量</span>
                <p style={{ margin: '4px 0 0', fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-primary)', fontWeight: 600 }}>{project.workpaper_count}</p>
              </div>
            </div>

            {/* Members */}
            {project.members.length > 0 && (
              <div style={{ marginTop: 'var(--gt-space-4)' }}>
                <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', display: 'block', marginBottom: 'var(--gt-space-2)' }}>项目组成员</span>
                <div style={{ display: 'flex', gap: 'var(--gt-space-2)', flexWrap: 'wrap' }}>
                  {project.members.map((m, i) => (
                    <span
                      key={i}
                      style={{
                        display: 'inline-block',
                        padding: 'var(--gt-space-1) var(--gt-space-3)',
                        borderRadius: 'var(--gt-radius-sm)',
                        backgroundColor: 'rgba(75,45,119,0.08)',
                        fontSize: 'var(--gt-font-sm)',
                        color: 'var(--gt-text-primary)',
                      }}
                    >
                      {m.user_id}（{ROLE_LABELS[m.role] ?? m.role}）
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Template IDs */}
            {project.template_ids.length > 0 && (
              <div style={{ marginTop: 'var(--gt-space-4)' }}>
                <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', display: 'block', marginBottom: 'var(--gt-space-2)' }}>关联模板</span>
                <div style={{ display: 'flex', gap: 'var(--gt-space-2)', flexWrap: 'wrap' }}>
                  {project.template_ids.map((tid) => (
                    <span
                      key={tid}
                      style={{
                        display: 'inline-block',
                        padding: 'var(--gt-space-1) var(--gt-space-3)',
                        borderRadius: 'var(--gt-radius-sm)',
                        backgroundColor: 'rgba(0,148,179,0.08)',
                        fontSize: 'var(--gt-font-sm)',
                        color: 'var(--gt-text-primary)',
                      }}
                    >
                      {tid}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Review summary */}
      {summary && <ReviewSummarySection summary={summary} />}

      {/* Link workpaper / template */}
      <section aria-labelledby="link-actions-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
        <div className="gt-card">
          <div className="gt-card-header">
            <h3 id="link-actions-heading" className="gt-h4" style={{ margin: 0, color: 'var(--gt-primary)' }}>关联操作</h3>
          </div>
          <div className="gt-card-content">
            <div className="gt-grid gt-grid-2" style={{ gap: 'var(--gt-space-4)' }}>
              {/* Link workpaper */}
              <div>
                <label htmlFor="link-workpaper" style={{ display: 'block', fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-1)' }}>
                  关联底稿
                </label>
                <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
                  <input
                    id="link-workpaper"
                    type="text"
                    value={linkWorkpaperId}
                    onChange={(e) => setLinkWorkpaperId(e.target.value)}
                    placeholder="底稿ID"
                    style={{ flex: 1, padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-sm)', border: '1px solid #d0d0d0', fontSize: 'var(--gt-font-sm)' }}
                  />
                  <button
                    className="gt-button gt-button--primary"
                    onClick={handleLinkWorkpaper}
                    disabled={loading || !linkWorkpaperId.trim()}
                    aria-label="关联底稿到项目"
                  >
                    关联
                  </button>
                </div>
              </div>

              {/* Link template */}
              <div>
                <label htmlFor="link-template" style={{ display: 'block', fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-1)' }}>
                  关联模板
                </label>
                <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
                  <input
                    id="link-template"
                    type="text"
                    value={linkTemplateId}
                    onChange={(e) => setLinkTemplateId(e.target.value)}
                    placeholder="模板ID"
                    style={{ flex: 1, padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-sm)', border: '1px solid #d0d0d0', fontSize: 'var(--gt-font-sm)' }}
                  />
                  <button
                    className="gt-button gt-button--primary"
                    onClick={handleLinkTemplate}
                    disabled={loading || !linkTemplateId.trim()}
                    aria-label="关联模板到项目"
                  >
                    关联
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Workpaper list with business cycle filter */}
      <section aria-labelledby="workpaper-list-heading">
        <div className="gt-card">
          <div className="gt-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--gt-space-2)' }}>
            <h3 id="workpaper-list-heading" className="gt-h4" style={{ margin: 0, color: 'var(--gt-primary)' }}>底稿列表</h3>
            <div>
              <label htmlFor="cycle-filter" className="sr-only" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0,0,0,0)' }}>
                按业务循环筛选
              </label>
              <select
                id="cycle-filter"
                value={cycleFilter}
                onChange={handleCycleChange}
                aria-label="按业务循环筛选底稿"
                style={{ padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-sm)', border: '1px solid #d0d0d0', fontSize: 'var(--gt-font-sm)' }}
              >
                {BUSINESS_CYCLES.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="gt-card-content">
            {workpapers.length === 0 ? (
              <p style={{ textAlign: 'center', color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)', padding: 'var(--gt-space-6) 0' }}>
                暂无底稿
              </p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="gt-table" style={{ width: '100%' }}>
                  <caption style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0,0,0,0)' }}>
                    项目底稿列表
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">文件名</th>
                      <th scope="col">底稿类型</th>
                      <th scope="col">业务循环</th>
                      <th scope="col">解析状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {workpapers.map((wp) => (
                      <tr key={wp.id}>
                        <td>{wp.filename}</td>
                        <td>{wp.workpaper_type || '-'}</td>
                        <td>{wp.business_cycle || '-'}</td>
                        <td>
                          <span className={wp.parse_status === 'success' ? 'gt-success' : wp.parse_status === 'error' ? 'gt-error' : ''}>
                            {wp.parse_status === 'success' ? '已解析' : wp.parse_status === 'error' ? '解析失败' : wp.parse_status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
};

// ─── Main ProjectPanel ───

const ProjectPanel: React.FC = () => {
  const [projects, setProjects] = useState<ProjectDetail[]>([]);
  const [selectedProject, setSelectedProject] = useState<ProjectDetail | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true);
    setError(null);
    try {
      const res = await projectApi.listProjects();
      setProjects(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || '加载项目列表失败');
    } finally {
      setLoadingProjects(false);
    }
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleCreateProject = async (data: ProjectCreateRequest) => {
    setIsSubmitting(true);
    setError(null);
    try {
      const res = await projectApi.createProject(data);
      setProjects((prev) => [res.data, ...prev]);
      setShowCreateForm(false);
    } catch (err: any) {
      setError(err?.response?.data?.detail || '创建项目失败');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSelectProject = async (projectId: string) => {
    setError(null);
    try {
      const res = await projectApi.getProject(projectId);
      setSelectedProject(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || '加载项目详情失败');
    }
  };

  const handleBack = () => {
    setSelectedProject(null);
    loadProjects();
  };

  // ── Detail view ──
  if (selectedProject) {
    return (
      <section aria-label="项目管理">
        <div className="gt-container gt-section">
          <ProjectDetailView project={selectedProject} onBack={handleBack} />
        </div>
      </section>
    );
  }

  // ── List view ──
  return (
    <section aria-label="项目管理">
      <div className="gt-container gt-section">
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--gt-space-5)' }}>
          <h2 className="gt-h3" style={{ margin: 0, color: 'var(--gt-text-primary)' }}>审计项目管理</h2>
          {!showCreateForm && (
            <button className="gt-button gt-button--primary" onClick={() => setShowCreateForm(true)} aria-label="创建新项目">
              + 创建项目
            </button>
          )}
        </div>

        {error && (
          <div role="alert" style={{ padding: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-4)', backgroundColor: 'rgba(220,53,69,0.08)', borderRadius: 'var(--gt-radius-sm)', color: 'var(--gt-danger)', fontSize: 'var(--gt-font-sm)' }}>
            {error}
          </div>
        )}

        {/* Create form */}
        {showCreateForm && (
          <div style={{ marginBottom: 'var(--gt-space-5)' }}>
            <CreateProjectForm onSubmit={handleCreateProject} onCancel={() => setShowCreateForm(false)} isSubmitting={isSubmitting} />
          </div>
        )}

        {/* Project list */}
        {loadingProjects ? (
          <div className="gt-card">
            <div className="gt-card-content" style={{ textAlign: 'center', padding: 'var(--gt-space-10)' }}>
              <p className="gt-loading" style={{ color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-base)' }}>加载中...</p>
            </div>
          </div>
        ) : projects.length === 0 ? (
          <div className="gt-card">
            <div className="gt-card-content" style={{ textAlign: 'center', padding: 'var(--gt-space-10)' }}>
              <p style={{ color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-base)' }}>暂无项目，请点击"创建项目"开始</p>
            </div>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="gt-table" style={{ width: '100%' }}>
              <caption style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0,0,0,0)' }}>
                审计项目列表
              </caption>
              <thead>
                <tr>
                  <th scope="col">项目名称</th>
                  <th scope="col">客户名称</th>
                  <th scope="col">审计期间</th>
                  <th scope="col">状态</th>
                  <th scope="col">底稿数量</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id}>
                    <td style={{ fontWeight: 600, color: 'var(--gt-text-primary)' }}>{p.name}</td>
                    <td>{p.client_name}</td>
                    <td>{p.audit_period}</td>
                    <td>{p.status}</td>
                    <td>{p.workpaper_count}</td>
                    <td>
                      <button
                        className="gt-button gt-button--secondary"
                        onClick={() => handleSelectProject(p.id)}
                        aria-label={`查看项目 ${p.name} 详情`}
                        style={{ fontSize: 'var(--gt-font-sm)', padding: 'var(--gt-space-1) var(--gt-space-3)' }}
                      >
                        查看详情
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
};

export default ProjectPanel;
