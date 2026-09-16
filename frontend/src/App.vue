<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { api } from './api';
import type { Entity, KnowledgeGraphNode, Project, ProjectScript, VideoFrame } from './types';

const steps = [
  { key: 'script', title: '剧本管理', description: '增加、删除和编辑剧幕' },
  { key: 'graph', title: '解析图谱', description: '解析全部剧幕并更新图谱' },
  { key: 'entities', title: '确认实体', description: '维护项目级实体资产' },
  { key: 'images', title: '生成模型图', description: '生成非概念实体参考图' },
  { key: 'frames', title: '生成分帧', description: '勾选剧幕后生成分帧' },
  { key: 'export', title: '导出素材', description: '勾选剧幕后导出 ZIP' },
] as const;

type StepKey = (typeof steps)[number]['key'];

const activeStep = ref<StepKey>('script');
const projects = ref<Project[]>([]);
const currentProject = ref<Project | null>(null);
const selectedScriptId = ref('');
const selectedEntityId = ref('');
const selectedNode = ref<KnowledgeGraphNode | null>(null);
const selectedEntityPrompt = ref('');
const selectedFrameScriptIds = ref<string[]>([]);
const selectedExportScriptIds = ref<string[]>([]);
const newProjectTitle = ref('新项目');
const loading = ref(false);
const message = ref('');
const error = ref('');

const selectedScript = computed(() => scripts.value.find((script) => script.id === selectedScriptId.value) ?? scripts.value[0] ?? null);
const scripts = computed(() => currentProject.value?.scripts ?? []);
const graph = computed(() => currentProject.value?.graph ?? { nodes: [], edges: [] });
const entities = computed(() => currentProject.value?.entities ?? []);
const visualEntities = computed(() => entities.value.filter((entity) => entity.type !== 'concept'));
const allFrames = computed(() => currentProject.value?.frames ?? []);
const selectedFrameKey = computed(() => JSON.stringify([...selectedFrameScriptIds.value].sort()));
const selectedFrames = computed(() =>
  allFrames.value.filter((frame) => frame.scope === selectedFrameKey.value || selectedFrameScriptIds.value.includes(frame.script_id ?? '')),
);
const exportsList = computed(() => currentProject.value?.exports ?? []);
const selectedEntity = computed(() => visualEntities.value.find((entity) => entity.id === selectedEntityId.value) ?? visualEntities.value[0] ?? null);
const canUseProject = computed(() => Boolean(currentProject.value));

watch(selectedEntity, (entity) => {
  selectedEntityPrompt.value = entity?.prompt ?? '';
});

watch(selectedScript, (script) => {
  if (!script) return;
  selectedScriptId.value = script.id;
});

function assetUrl(path?: string) {
  if (!path) return '';
  if (path.startsWith('http')) return path;
  const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api').replace('/api', '');
  return `${base}${path}`;
}

function setNotice(text: string) {
  message.value = text;
  error.value = '';
}

function setError(err: unknown) {
  message.value = '';
  error.value = err instanceof Error ? err.message : '操作失败';
}

async function run<T>(task: () => Promise<T>, success?: string): Promise<T | undefined> {
  loading.value = true;
  try {
    const result = await task();
    if (success) setNotice(success);
    return result;
  } catch (err) {
    setError(err);
    return undefined;
  } finally {
    loading.value = false;
  }
}

async function refreshProjects() {
  const data = await run(() => api.listProjects());
  if (data) projects.value = data;
}

function syncSelections() {
  const ids = scripts.value.map((script) => script.id);
  if (!selectedScriptId.value || !ids.includes(selectedScriptId.value)) {
    selectedScriptId.value = ids[0] ?? '';
  }
  selectedFrameScriptIds.value = selectedFrameScriptIds.value.filter((id) => ids.includes(id));
  selectedExportScriptIds.value = selectedExportScriptIds.value.filter((id) => ids.includes(id));
  if (selectedFrameScriptIds.value.length === 0) selectedFrameScriptIds.value = [...ids];
  if (selectedExportScriptIds.value.length === 0) selectedExportScriptIds.value = [...ids];
  selectedEntityId.value = visualEntities.value[0]?.id ?? '';
  selectedNode.value = graph.value.nodes[0] ?? null;
}

async function loadProject(projectId: string, step?: StepKey) {
  const data = await run(() => api.getProject(projectId));
  if (!data) return;
  currentProject.value = data;
  syncSelections();
  if (step) activeStep.value = step;
}

async function createProject() {
  const project = await run(() => api.createProject({ title: newProjectTitle.value || '新项目' }), '项目已创建');
  if (!project) return;
  currentProject.value = project;
  selectedScriptId.value = '';
  await refreshProjects();
}

async function renameProject(project: Project) {
  const updated = await run(() => api.updateProject(project.id, project.title), '项目已重命名');
  if (!updated) return;
  currentProject.value = updated;
  await refreshProjects();
}

async function deleteProject(project: Project) {
  if (!window.confirm(`删除项目“${project.title}”？此操作会删除本地素材文件。`)) return;
  await run(() => api.deleteProject(project.id), '项目已删除');
  await refreshProjects();
  currentProject.value = projects.value[0] ? await api.getProject(projects.value[0].id) : null;
  syncSelections();
}

async function addScene() {
  if (!currentProject.value) return;
  const index = scripts.value.length + 1;
  const project = await run(
    () =>
      api.addScript(currentProject.value!.id, {
        title: `第 ${index} 幕`,
        content: '',
      }),
    '已增加一幕',
  );
  if (!project) return;
  currentProject.value = project;
  const nextScripts = project.scripts ?? [];
  selectedScriptId.value = project.active_script_id ?? nextScripts[nextScripts.length - 1]?.id ?? '';
  syncSelections();
  await refreshProjects();
}

async function deleteScene() {
  if (!currentProject.value || !selectedScript.value) return;
  if (!window.confirm(`删除“${selectedScript.value.title}”？`)) return;
  const project = await run(() => api.deleteScript(currentProject.value!.id, selectedScript.value!.id), '剧幕已删除');
  if (!project) return;
  currentProject.value = project;
  syncSelections();
  await refreshProjects();
}

async function saveScript(script: ProjectScript) {
  if (!currentProject.value) return;
  await run(
    () =>
      api.updateScript(currentProject.value!.id, script.id, {
        title: script.title,
        content: script.content,
      }),
    '剧幕已保存',
  );
  await refreshProjects();
}

async function analyzeScripts() {
  if (!currentProject.value) return;
  if (scripts.value.length === 0) {
    setError(new Error('请先增加至少一幕剧本'));
    return;
  }
  const project = await run(() => api.analyzeProject(currentProject.value!.id), '全部剧本已解析，知识图谱已更新');
  if (!project) return;
  currentProject.value = project;
  syncSelections();
  activeStep.value = 'graph';
  await refreshProjects();
}

async function saveEntity(entity: Entity) {
  const updated = await run(() => api.updateEntity(entity.id, entity), '实体已保存');
  if (!updated || !currentProject.value?.entities) return;
  currentProject.value.entities = currentProject.value.entities.map((item) => (item.id === updated.id ? updated : item));
}

function chooseEntity(entity: Entity) {
  selectedEntityId.value = entity.id;
  selectedEntityPrompt.value = entity.prompt ?? '';
}

async function generateImage() {
  if (!selectedEntity.value) return;
  const updated = await run(
    () => api.generateEntityImage(selectedEntity.value!.id, selectedEntityPrompt.value),
    '实体模型图已生成',
  );
  if (!updated || !currentProject.value?.entities) return;
  currentProject.value.entities = currentProject.value.entities.map((item) => (item.id === updated.id ? updated : item));
  await loadProject(currentProject.value.id, 'images');
}

async function uploadReference(event: Event) {
  if (!selectedEntity.value) return;
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const updated = await run(() => api.uploadReferenceImage(selectedEntity.value!.id, file), '参考图片已上传');
  input.value = '';
  if (!updated || !currentProject.value?.entities) return;
  currentProject.value.entities = currentProject.value.entities.map((item) => (item.id === updated.id ? updated : item));
}

async function setMainImage(entity: Entity, imageId: string) {
  await saveEntity({ ...entity, main_image_id: imageId, status: 'image_ready' });
  await loadProject(entity.project_id, 'images');
}

async function deleteImage(imageId: string) {
  if (!selectedEntity.value) return;
  if (!window.confirm('删除这张图片？')) return;
  const updated = await run(() => api.deleteEntityImage(imageId), '图片已删除');
  if (!updated || !currentProject.value?.entities) return;
  currentProject.value.entities = currentProject.value.entities.map((item) => (item.id === updated.id ? updated : item));
}

function toggleAll(target: 'frame' | 'export') {
  const ids = scripts.value.map((script) => script.id);
  const selected = target === 'frame' ? selectedFrameScriptIds : selectedExportScriptIds;
  selected.value = selected.value.length === ids.length ? [] : [...ids];
}

async function generateFrames() {
  if (!currentProject.value) return;
  if (selectedFrameScriptIds.value.length === 0) {
    setError(new Error('请至少选择一幕剧本'));
    return;
  }
  const data = await run(() => api.generateFrames(currentProject.value!.id, selectedFrameScriptIds.value), '分帧已生成');
  if (!data || !currentProject.value) return;
  await loadProject(currentProject.value.id, 'frames');
}

async function saveFrame(frame: VideoFrame) {
  const updated = await run(
    () =>
      api.updateFrame(frame.id, {
        description: frame.description,
        camera: frame.camera,
        mood: frame.mood,
        entity_ids: frame.entity_ids,
      }),
    '帧描述已保存',
  );
  if (!updated || !currentProject.value?.frames) return;
  currentProject.value.frames = currentProject.value.frames.map((item) => (item.id === updated.id ? updated : item));
}

async function exportProject() {
  if (!currentProject.value) return;
  if (selectedExportScriptIds.value.length === 0) {
    setError(new Error('请至少选择一幕剧本'));
    return;
  }
  await run(() => api.exportProject(currentProject.value!.id, selectedExportScriptIds.value), '素材包已导出');
  await loadProject(currentProject.value.id, 'export');
  await refreshProjects();
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
  setNotice('已复制到剪贴板');
}

onMounted(async () => {
  await refreshProjects();
  if (projects.value[0]) await loadProject(projects.value[0].id);
});
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">W2V</span>
        <div>
          <strong>Word2Video</strong>
          <small>项目级 AI 视频素材工作台</small>
        </div>
      </div>

      <nav class="steps">
        <button
          v-for="(step, index) in steps"
          :key="step.key"
          class="step"
          :class="{ active: activeStep === step.key }"
          :disabled="step.key !== 'script' && !canUseProject"
          @click="activeStep = step.key"
        >
          <span>{{ index + 1 }}</span>
          <div>
            <strong>{{ step.title }}</strong>
            <small>{{ step.description }}</small>
          </div>
        </button>
      </nav>

      <section class="project-history">
        <h2>项目</h2>
        <div class="project-create">
          <input v-model="newProjectTitle" placeholder="项目名称" />
          <button class="secondary" @click="createProject">创建</button>
        </div>
        <article v-for="project in projects" :key="project.id" class="project-row" :class="{ active: currentProject?.id === project.id }">
          <button class="history-item" @click="loadProject(project.id)">
            <strong>{{ project.title }}</strong>
            <small>{{ project.script_count }} 幕 · {{ project.entity_count }} 实体 · {{ project.frame_count }} 帧</small>
          </button>
          <div class="project-actions">
            <input v-model="project.title" @blur="renameProject(project)" @keyup.enter="renameProject(project)" />
            <button class="icon-button" title="删除项目" @click="deleteProject(project)">×</button>
          </div>
        </article>
        <p v-if="projects.length === 0" class="muted">暂无项目，请先创建项目。</p>
      </section>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">Local FastAPI + Vue + SQLite</p>
          <h1>{{ currentProject?.title ?? '新建 AI 视频素材项目' }}</h1>
        </div>
        <div class="status-area">
          <span v-if="loading" class="pill">处理中...</span>
          <span v-if="currentProject" class="pill success">{{ currentProject.progress }}%</span>
        </div>
      </header>

      <p v-if="message" class="notice">{{ message }}</p>
      <p v-if="error" class="error">{{ error }}</p>

      <section v-if="activeStep === 'script'" class="panel script-panel">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 1</p>
            <h2>剧本管理</h2>
          </div>
          <div class="toolbar">
            <button class="secondary" :disabled="!currentProject" @click="addScene">增加幕</button>
            <button class="secondary" :disabled="!selectedScript" @click="deleteScene">删除幕</button>
          </div>
        </div>

        <div v-if="scripts.length" class="script-list">
          <button
            v-for="script in scripts"
            :key="script.id"
            class="script-item"
            :class="{ active: script.id === selectedScriptId }"
            @click="selectedScriptId = script.id"
          >
            <strong>{{ script.order_index }}. {{ script.title || '未命名剧幕' }}</strong>
            <small>{{ script.status }} · {{ script.word_count }} 字</small>
          </button>
        </div>
        <div v-else class="empty compact">
          <p>当前项目还没有剧幕，点击“增加幕”开始。</p>
        </div>

        <template v-if="selectedScript">
          <label>
            剧本标题
            <input v-model="selectedScript.title" @blur="saveScript(selectedScript)" @keyup.enter="saveScript(selectedScript)" />
          </label>
          <label>
            剧本文字
            <textarea v-model="selectedScript.content" rows="16" @blur="saveScript(selectedScript)" />
          </label>
          <footer class="panel-footer">
            <span>{{ selectedScript.content.length }} 字</span>
            <button class="secondary" :disabled="loading" @click="saveScript(selectedScript)">保存剧幕</button>
          </footer>
        </template>
      </section>

      <section v-if="activeStep === 'graph'" class="panel">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 2</p>
            <h2>项目级知识图谱</h2>
          </div>
          <button class="primary" :disabled="!currentProject || scripts.length === 0 || loading" @click="analyzeScripts">解析剧本</button>
        </div>
        <div v-if="graph.nodes.length" class="graph-layout">
          <svg class="graph-canvas" viewBox="0 0 920 760" role="img">
            <line
              v-for="edge in graph.edges"
              :key="edge.id"
              :x1="graph.nodes.find((node) => node.id === edge.source_node_id)?.x"
              :y1="graph.nodes.find((node) => node.id === edge.source_node_id)?.y"
              :x2="graph.nodes.find((node) => node.id === edge.target_node_id)?.x"
              :y2="graph.nodes.find((node) => node.id === edge.target_node_id)?.y"
              stroke="#94a3b8"
              stroke-width="2"
            />
            <g
              v-for="node in graph.nodes"
              :key="node.id"
              class="graph-node"
              :class="{ changed: node.change_state !== 'existing' }"
              :transform="`translate(${node.x}, ${node.y})`"
              @click="selectedNode = node"
            >
              <circle r="46" />
              <text text-anchor="middle" y="5">{{ node.name.slice(0, 5) }}</text>
            </g>
          </svg>
          <aside class="detail-card">
            <h3>{{ selectedNode?.name ?? graph.nodes[0].name }}</h3>
            <p>{{ selectedNode?.description ?? graph.nodes[0].description }}</p>
            <small>类型：{{ selectedNode?.type ?? graph.nodes[0].type }}</small>
          </aside>
        </div>
        <div v-else class="empty">
          <p>还没有知识图谱。请先增加剧幕并点击“解析剧本”。</p>
        </div>
      </section>

      <section v-if="activeStep === 'entities'" class="panel">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 3</p>
            <h2>项目级实体对象</h2>
          </div>
          <button class="secondary" @click="activeStep = 'images'">进入图片生成</button>
        </div>
        <div class="entity-grid">
          <article v-for="entity in entities" :key="entity.id" class="entity-card">
            <div class="entity-head">
              <input v-model="entity.name" />
              <select v-model="entity.type">
                <option value="character">人物</option>
                <option value="object">物品</option>
                <option value="scene">场景</option>
                <option value="concept">概念</option>
              </select>
            </div>
            <textarea v-model="entity.description" rows="4" />
            <div class="card-actions">
              <span class="pill">{{ entity.status }} · {{ entity.source_script_count }} 幕</span>
              <button class="secondary" @click="saveEntity(entity)">保存</button>
            </div>
          </article>
        </div>
      </section>

      <section v-if="activeStep === 'images'" class="panel image-step">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 4</p>
            <h2>非概念实体模型参考图</h2>
          </div>
          <button class="secondary" @click="activeStep = 'frames'">进入分帧</button>
        </div>
        <div class="image-layout">
          <div class="entity-list">
            <button
              v-for="entity in visualEntities"
              :key="entity.id"
              class="entity-row"
              :class="{ active: selectedEntity?.id === entity.id }"
              @click="chooseEntity(entity)"
            >
              <strong>{{ entity.name }}</strong>
              <small>{{ entity.type }} · {{ entity.images.length }} 张图</small>
            </button>
          </div>
          <div v-if="selectedEntity" class="image-workbench">
            <h3>{{ selectedEntity.name }}</h3>
            <p>{{ selectedEntity.description }}</p>
            <label>
              图片生成提示词
              <textarea v-model="selectedEntityPrompt" rows="5" />
            </label>
            <div class="toolbar">
              <button class="primary" :disabled="loading" @click="generateImage">生成模型图</button>
              <label class="upload-button">
                上传参考图
                <input type="file" accept="image/*" @change="uploadReference" />
              </label>
            </div>
            <div class="gallery">
              <article
                v-for="image in selectedEntity.images"
                :key="image.id"
                class="image-card"
                :class="{ main: selectedEntity.main_image_id === image.id }"
              >
                <img :src="assetUrl(image.image_url)" :alt="selectedEntity.name" />
                <div class="image-actions">
                  <button class="secondary" @click="setMainImage(selectedEntity, image.id)">
                    {{ selectedEntity.main_image_id === image.id ? '主参考图' : '设为主图' }}
                  </button>
                  <button class="danger" @click="deleteImage(image.id)">删除</button>
                </div>
              </article>
            </div>
          </div>
          <div v-else class="empty compact">
            <p>暂无可生成模型图的非概念实体。</p>
          </div>
        </div>
      </section>

      <section v-if="activeStep === 'frames'" class="panel">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 5</p>
            <h2>视频分帧描述</h2>
          </div>
          <button class="primary" :disabled="!currentProject || loading" @click="generateFrames">生成分帧</button>
        </div>
        <div class="scope-bar">
          <button class="secondary" @click="toggleAll('frame')">
            {{ selectedFrameScriptIds.length === scripts.length ? '取消全选' : '全选剧幕' }}
          </button>
          <label v-for="script in scripts" :key="script.id">
            <input v-model="selectedFrameScriptIds" type="checkbox" :value="script.id" />
            {{ script.title }}
          </label>
        </div>
        <div class="frame-list">
          <article v-for="frame in selectedFrames" :key="frame.id" class="frame-card">
            <div class="frame-index">Frame {{ frame.frame_index }} · {{ frame.script_title }}</div>
            <textarea v-model="frame.description" rows="4" />
            <div class="form-grid">
              <input v-model="frame.camera" placeholder="镜头语言" />
              <input v-model="frame.mood" placeholder="情绪氛围" />
            </div>
            <div class="frame-entities">
              <span v-for="entity in frame.entities" :key="entity.id">{{ entity.name }}</span>
            </div>
            <pre>{{ frame.prompt }}</pre>
            <div class="card-actions">
              <button class="secondary" @click="saveFrame(frame)">保存</button>
              <button class="secondary" @click="copyText(frame.prompt)">复制提示词</button>
            </div>
          </article>
        </div>
      </section>

      <section v-if="activeStep === 'export'" class="panel">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 6</p>
            <h2>导出素材包</h2>
          </div>
          <button class="primary" :disabled="!currentProject || loading" @click="exportProject">导出 ZIP</button>
        </div>
        <div class="scope-bar">
          <button class="secondary" @click="toggleAll('export')">
            {{ selectedExportScriptIds.length === scripts.length ? '取消全选' : '全选剧幕' }}
          </button>
          <label v-for="script in scripts" :key="script.id">
            <input v-model="selectedExportScriptIds" type="checkbox" :value="script.id" />
            {{ script.title }}
          </label>
        </div>
        <div class="export-summary">
          <div><strong>{{ scripts.length }}</strong><span>项目剧幕</span></div>
          <div><strong>{{ entities.length }}</strong><span>共享实体</span></div>
          <div><strong>{{ selectedFrames.length }}</strong><span>当前展示帧</span></div>
        </div>
        <div class="export-list">
          <a v-for="item in exportsList" :key="item.id" :href="assetUrl(item.file_url)" download>
            下载素材包 · {{ item.frame_count }} 帧 · {{ new Date(item.created_at).toLocaleString() }}
          </a>
        </div>
      </section>
    </main>

    <aside class="context-panel">
      <section class="summary-card">
        <h2>项目摘要</h2>
        <p v-if="!currentProject">还没有选中的项目。</p>
        <template v-else>
          <div class="metric"><span>状态</span><strong>{{ currentProject.status }}</strong></div>
          <div class="metric"><span>当前剧幕</span><strong>{{ selectedScript?.title ?? '未选择' }}</strong></div>
          <div class="metric"><span>总剧幕</span><strong>{{ currentProject.script_count }}</strong></div>
          <div class="metric"><span>实体</span><strong>{{ currentProject.entity_count }}</strong></div>
          <div class="metric"><span>已配图实体</span><strong>{{ currentProject.completed_entity_image_count }}</strong></div>
          <div class="metric"><span>分帧</span><strong>{{ currentProject.frame_count }}</strong></div>
        </template>
      </section>

      <section class="summary-card">
        <h2>下一步</h2>
        <p v-if="activeStep === 'script'">增加幕并编辑剧本内容，标题会同步到剧幕列表。</p>
        <p v-else-if="activeStep === 'graph'">点击“解析剧本”会解析项目中全部剧幕。</p>
        <p v-else-if="activeStep === 'entities'">维护项目级实体，实体图会被所有剧幕共用。</p>
        <p v-else-if="activeStep === 'images'">这里只展示人物、物品、场景等非概念实体。</p>
        <p v-else-if="activeStep === 'frames'">勾选一个或多个剧幕后生成分帧。</p>
        <p v-else>勾选一个或多个剧幕后导出 ZIP。</p>
      </section>
    </aside>
  </div>
</template>
