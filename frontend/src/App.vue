<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { api } from './api';
import type { Entity, KnowledgeGraphNode, Project, VideoFrame } from './types';

const steps = [
  { key: 'script', title: '输入剧本', description: '粘贴文字剧本并创建项目' },
  { key: 'graph', title: '解析图谱', description: '查看知识图谱和对象关系' },
  { key: 'entities', title: '确认实体', description: '修正人物、物品、场景' },
  { key: 'images', title: '生成模型图', description: '生成或上传实体参考图' },
  { key: 'frames', title: '生成分帧', description: '获得帧级画面提示词' },
  { key: 'export', title: '导出素材', description: '下载结构化素材包' },
] as const;

type StepKey = (typeof steps)[number]['key'];

const activeStep = ref<StepKey>('script');
const projects = ref<Project[]>([]);
const currentProject = ref<Project | null>(null);
const selectedEntityId = ref<string>('');
const selectedNode = ref<KnowledgeGraphNode | null>(null);
const loading = ref(false);
const message = ref('');
const error = ref('');

const form = ref({
  title: '',
  content_type: '故事短片',
  script:
    '小明在雨后的城市街道上发现一把发光的钥匙。钥匙指引他来到一间旧书店，店里的老人告诉他，这把钥匙可以打开隐藏在学校天台上的星空之门。小明背着背包穿过空荡的走廊，在天台上举起钥匙，城市的灯光逐渐变成璀璨星河。',
});

const selectedEntity = computed(() => {
  const entities = currentProject.value?.entities ?? [];
  return entities.find((entity) => entity.id === selectedEntityId.value) ?? entities[0] ?? null;
});

const canUseProject = computed(() => Boolean(currentProject.value));
const graph = computed(() => currentProject.value?.graph ?? { nodes: [], edges: [] });
const entities = computed(() => currentProject.value?.entities ?? []);
const frames = computed(() => currentProject.value?.frames ?? []);
const exportsList = computed(() => currentProject.value?.exports ?? []);
const selectedEntityPrompt = ref('');

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

async function loadProject(projectId: string, step?: StepKey) {
  const data = await run(() => api.getProject(projectId));
  if (!data) return;
  currentProject.value = data;
  selectedEntityId.value = data.entities?.[0]?.id ?? '';
  selectedEntityPrompt.value = data.entities?.[0]?.prompt ?? '';
  if (step) activeStep.value = step;
}

async function createProject() {
  if (form.value.script.trim().length < 20) {
    setError(new Error('剧本至少需要 20 个字'));
    return;
  }
  const project = await run(
    () =>
      api.createProject({
        title: form.value.title || undefined,
        script: form.value.script,
        content_type: form.value.content_type,
      }),
    '项目已创建',
  );
  if (!project) return;
  currentProject.value = project;
  await refreshProjects();
  activeStep.value = 'graph';
}

async function analyzeProject() {
  if (!currentProject.value) return;
  const project = await run(() => api.analyzeProject(currentProject.value!.id), '知识图谱和实体已生成');
  if (!project) return;
  currentProject.value = project;
  selectedEntityId.value = project.entities?.[0]?.id ?? '';
  selectedEntityPrompt.value = project.entities?.[0]?.prompt ?? '';
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

async function generateFrames() {
  if (!currentProject.value) return;
  const data = await run(() => api.generateFrames(currentProject.value!.id), '分帧描述已生成');
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
  await run(() => api.exportProject(currentProject.value!.id), '素材包已导出');
  await loadProject(currentProject.value.id, 'export');
  await refreshProjects();
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
  setNotice('已复制到剪贴板');
}

onMounted(async () => {
  await refreshProjects();
  if (projects.value[0]) {
    await loadProject(projects.value[0].id);
  }
});
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">W2V</span>
        <div>
          <strong>Word2Video</strong>
          <small>AI 视频素材工作台</small>
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
        <h2>项目历史</h2>
        <button
          v-for="project in projects"
          :key="project.id"
          class="history-item"
          :class="{ active: currentProject?.id === project.id }"
          @click="loadProject(project.id)"
        >
          <strong>{{ project.title }}</strong>
          <small>{{ project.status }} · {{ project.entity_count }} 个实体 · {{ project.frame_count }} 帧</small>
        </button>
        <p v-if="projects.length === 0" class="muted">暂无项目，先创建一个剧本项目。</p>
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
            <h2>输入文字剧本</h2>
          </div>
          <button class="primary" :disabled="loading" @click="createProject">创建项目</button>
        </div>
        <div class="form-grid">
          <label>
            项目标题
            <input v-model="form.title" placeholder="默认使用剧本前 24 个字" />
          </label>
          <label>
            内容类型
            <select v-model="form.content_type">
              <option>故事短片</option>
              <option>广告脚本</option>
              <option>教育讲解</option>
              <option>产品介绍</option>
            </select>
          </label>
        </div>
        <label>
          剧本文字
          <textarea v-model="form.script" rows="18" />
        </label>
        <footer class="panel-footer">
          <span>{{ form.script.length }} 字</span>
          <button class="secondary" :disabled="!currentProject || loading" @click="analyzeProject">解析当前项目</button>
        </footer>
      </section>

      <section v-if="activeStep === 'graph'" class="panel">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 2</p>
            <h2>知识图谱</h2>
          </div>
          <button class="primary" :disabled="!currentProject || loading" @click="analyzeProject">重新解析</button>
        </div>
        <div v-if="graph.nodes.length" class="graph-layout">
          <svg class="graph-canvas" viewBox="0 0 920 560" role="img">
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
          <p>还没有知识图谱。请先创建项目并点击解析。</p>
        </div>
      </section>

      <section v-if="activeStep === 'entities'" class="panel">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 3</p>
            <h2>确认实体对象</h2>
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
              <span class="pill">{{ entity.status }}</span>
              <button class="secondary" @click="saveEntity(entity)">保存</button>
            </div>
          </article>
        </div>
      </section>

      <section v-if="activeStep === 'images'" class="panel image-step">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 4</p>
            <h2>实体模型参考图</h2>
          </div>
          <button class="secondary" @click="activeStep = 'frames'">进入分帧</button>
        </div>
        <div class="image-layout">
          <div class="entity-list">
            <button
              v-for="entity in entities"
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
              <article v-for="image in selectedEntity.images" :key="image.id" class="image-card">
                <img :src="assetUrl(image.image_url)" :alt="selectedEntity.name" />
                <button class="secondary" @click="setMainImage(selectedEntity, image.id)">
                  {{ selectedEntity.main_image_id === image.id ? '主参考图' : '设为主图' }}
                </button>
              </article>
            </div>
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
        <div class="frame-list">
          <article v-for="frame in frames" :key="frame.id" class="frame-card">
            <div class="frame-index">Frame {{ frame.frame_index }}</div>
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
        <div class="export-summary">
          <div><strong>{{ entities.length }}</strong><span>实体对象</span></div>
          <div><strong>{{ frames.length }}</strong><span>分帧描述</span></div>
          <div><strong>{{ exportsList.length }}</strong><span>导出记录</span></div>
        </div>
        <div class="export-list">
          <a v-for="item in exportsList" :key="item.id" :href="assetUrl(item.file_url)" download>
            下载素材包 · {{ new Date(item.created_at).toLocaleString() }}
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
          <div class="metric"><span>实体</span><strong>{{ currentProject.entity_count }}</strong></div>
          <div class="metric"><span>已配图实体</span><strong>{{ currentProject.completed_entity_image_count }}</strong></div>
          <div class="metric"><span>分帧</span><strong>{{ currentProject.frame_count }}</strong></div>
        </template>
      </section>

      <section class="summary-card">
        <h2>下一步</h2>
        <p v-if="activeStep === 'script'">创建项目后进入知识图谱解析。</p>
        <p v-else-if="activeStep === 'graph'">确认图谱中的实体和关系是否合理。</p>
        <p v-else-if="activeStep === 'entities'">修正实体名称、类型和描述。</p>
        <p v-else-if="activeStep === 'images'">为每个实体生成或上传主参考图。</p>
        <p v-else-if="activeStep === 'frames'">生成分帧后可复制单帧提示词。</p>
        <p v-else>导出 ZIP 后即可带到其他 AI 平台继续生成画面。</p>
      </section>
    </aside>
  </div>
</template>
