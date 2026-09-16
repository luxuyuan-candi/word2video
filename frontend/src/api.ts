import type { Entity, Project, VideoFrame } from './types';

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
  createProject: (payload: { title?: string; script: string; content_type?: string }) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(payload) }),
  getProject: (projectId: string) => request<Project>(`/projects/${projectId}`),
  analyzeProject: (projectId: string) => request<Project>(`/projects/${projectId}/analyze`, { method: 'POST' }),
  updateEntity: (entityId: string, payload: Partial<Entity>) =>
    request<Entity>(`/entities/${entityId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  generateEntityImage: (entityId: string, prompt?: string) =>
    request<Entity>(`/entities/${entityId}/images`, { method: 'POST', body: JSON.stringify({ prompt }) }),
  uploadReferenceImage: (entityId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<Entity>(`/entities/${entityId}/reference-images`, { method: 'POST', body: form });
  },
  generateFrames: (projectId: string) =>
    request<VideoFrame[]>(`/projects/${projectId}/frames/generate`, { method: 'POST' }),
  updateFrame: (frameId: string, payload: Partial<VideoFrame>) =>
    request<VideoFrame>(`/frames/${frameId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  exportProject: (projectId: string) =>
    request<{ id: string; file_url: string; created_at: string }>(`/projects/${projectId}/export`, { method: 'POST' }),
};
