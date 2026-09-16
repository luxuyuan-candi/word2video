import type { Entity, FrameScope, Project, ProjectScript, VideoFrame } from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: options.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? 'Request failed');
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; database: string; storage: string }>('/health'),
  listProjects: () => request<Project[]>('/projects'),
  createProject: (payload: { title?: string; script_title?: string; script: string; content_type?: string }) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(payload) }),
  getProject: (projectId: string) => request<Project>(`/projects/${projectId}`),
  addScript: (projectId: string, payload: { title?: string; content: string; content_type?: string }) =>
    request<Project>(`/projects/${projectId}/scripts`, { method: 'POST', body: JSON.stringify(payload) }),
  updateScript: (projectId: string, scriptId: string, payload: Partial<ProjectScript>) =>
    request<ProjectScript>(`/projects/${projectId}/scripts/${scriptId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  setActiveScript: (projectId: string, scriptId: string) =>
    request<Project>(`/projects/${projectId}/active-script`, {
      method: 'PATCH',
      body: JSON.stringify({ script_id: scriptId }),
    }),
  analyzeProject: (projectId: string) => request<Project>(`/projects/${projectId}/analyze`, { method: 'POST' }),
  analyzeScript: (projectId: string, scriptId: string) =>
    request<Project>(`/projects/${projectId}/scripts/${scriptId}/analyze`, { method: 'POST' }),
  updateEntity: (entityId: string, payload: Partial<Entity>) =>
    request<Entity>(`/entities/${entityId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  mergeEntity: (entityId: string, targetEntityId: string) =>
    request<Entity>(`/entities/${entityId}/merge`, {
      method: 'POST',
      body: JSON.stringify({ target_entity_id: targetEntityId }),
    }),
  generateEntityImage: (entityId: string, prompt?: string) =>
    request<Entity>(`/entities/${entityId}/images`, { method: 'POST', body: JSON.stringify({ prompt }) }),
  uploadReferenceImage: (entityId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<Entity>(`/entities/${entityId}/reference-images`, { method: 'POST', body: form });
  },
  generateFrames: (projectId: string, scope: FrameScope, scriptId?: string) =>
    request<VideoFrame[]>(`/projects/${projectId}/frames/generate`, {
      method: 'POST',
      body: JSON.stringify({ scope, script_id: scriptId }),
    }),
  getFrames: (projectId: string, scope?: FrameScope, scriptId?: string) => {
    const params = new URLSearchParams();
    if (scope) params.set('scope', scope);
    if (scriptId) params.set('scriptId', scriptId);
    const query = params.toString();
    return request<VideoFrame[]>(`/projects/${projectId}/frames${query ? `?${query}` : ''}`);
  },
  updateFrame: (frameId: string, payload: Partial<VideoFrame>) =>
    request<VideoFrame>(`/frames/${frameId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  exportProject: (projectId: string, scope: FrameScope, scriptId?: string) =>
    request<{ id: string; file_url: string; scope: FrameScope; frame_count: number; created_at: string }>(
      `/projects/${projectId}/export`,
      { method: 'POST', body: JSON.stringify({ scope, script_id: scriptId }) },
    ),
};
