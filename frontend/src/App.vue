<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { api } from './api';
import type { Entity, FrameScope, KnowledgeGraphNode, Project, ProjectScript, VideoFrame } from './types';

const steps = [
  { key: 'script', title: '剧本管理', description: '项目下新增和切换剧本' },
  { key: 'graph', title: '解析图谱', description: '增量更新项目级知识图谱' },
  { key: 'entities', title: '确认实体', description: '维护项目级实体资产' },
  { key: 'images', title: '生成模型图', description: '生成或上传实体参考图' },
  { key: 'frames', title: '生成分帧', description: '当前剧本或总剧本分帧' },
  { key: 'export', title: '导出素材', description: '按帧目录导出素材包' },
] as const;

type StepKey = (typeof steps)[number]['key'];

const activeStep = ref<StepKey>('script');
const projects = ref<Project[]>([]);
const currentProject = ref<Project | null>(null);
const selectedEntityId = ref('');
const selectedNode = ref<KnowledgeGraphNode | null>(null);
const selectedEntityPrompt = ref('');
const frameScope = ref<FrameScope>('current_script');
const exportScope = ref<FrameScope>('current_script');
const loading = ref(false);
const message = ref('');
const error = ref('');

const form = ref({
  title: '',
  script_title: '',
  content_type: '故事短片',
  script:
    '小明在雨后的城市街道上发现一把发光的钥匙。钥匙指引他来到一间旧书店，店里的老人告诉他，这把钥匙可以打开隐藏在学校天台上的星空之门。小明背着背包穿过空荡的走廊，在天台上举起钥匙，城市的灯光逐渐变成璀璨星河。',
});

const activeScript = computed(() => currentProject.value?.active_script ?? null);
const scripts = computed(() => currentProject.value?.scripts ?? []);
const graph = computed(() => currentProject.value?.graph ?? { nodes: [], edges: [] });
const entities = computed(() => currentProject.value?.entities ?? []);
const allFrames = computed(() => currentProject.value?.frames ?? []);
const currentFrames = computed(() =>
  allFrames.value.filter((frame) => {
    if (frame.scope !== frameScope.value) return false;
    if (frameScope.value === 'current_script') return frame.script_id === activeScript.value?.id;
    return true;
  }),
);
const exportsList = computed(() => currentProject.value?.exports ?? []);
const selectedEntity = computed(() => {
  return entities.value.find((entity) => entity.id === selectedEntityId.value) ?? entities.value[0] ?? null;
});
const canUseProject = computed(() => Boolean(currentProject.value));

watch(selectedEntity, (entity) => {
  selectedEntityPrompt.value = entity?.prompt ?? '';
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

async function loadProject(projectId: string, step?: StepKey) {
  const data = await run(() => api.getProject(projectId));
  if (!data) return;
  currentProject.value = data;
  selectedEntityId.value = data.entities?.[0]?.id ?? '';
  selectedEntityPrompt.value = data.entities?.[0]?.prompt ?? '';
  selectedNode.value = data.graph?.nodes[0] ?? null;
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
        script_title: form.value.script_title || undefined,
        script: form.value.script,
        content_type: form.value.content_type,
      }),
    '项目已创建，首个剧本已加入项目',
  );
  if (!project) return;
  currentProject.value = project;
  await refreshProjects();
  activeStep.value = 'graph';
}

async function addScript() {
  if (!currentProject.value) return;
  if (form.value.script.trim().length < 20) {
    setError(new Error('新增剧本至少需要 20 个字'));
    return;
  }
  const project = await run(
    () =>
      api.addScript(currentProject.value!.id, {
        title: form.value.script_title || undefined,
        content: form.value.script,
        content_type: form.value.content_type,
      }),
    '新剧本已加入当前项目',
  );
  if (!project) return;
  currentProject.value = project;
  await refreshProjects();
}

async function setActiveScript(script: ProjectScript) {
  if (!currentProject.value) return;
  const project = await run(() => api.setActiveScript(currentProject.value!.id, script.id), '已切换当前剧本');
  if (!project) return;
  currentProject.value = project;
  form.value.script_title = script.title;
  form.value.script = script.content;
}

async function analyzeActiveScript() {
  if (!currentProject.value || !activeScript.value) return;
  const project = await run(
    () => api.analyzeScript(currentProject.value!.id, activeScript.value!.id),
    '当前剧本已解析，项目级图谱和实体已增量更新',
  );
  if (!project) return;
  currentProject.value = project;
  selectedEntityId.value = project.entities?.[0]?.id ?? '';
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
  if (frameScope.value === 'current_script' && !activeScript.value) {
    setError(new Error('请先选择当前剧本'));
    return;
  }
  const data = await run(
    () => api.generateFrames(currentProject.value!.id, frameScope.value, activeScript.value?.id),
    frameScope.value === 'current_script' ? '当前剧本分帧已生成' : '总剧本分帧已生成',
  );
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
  if (exportScope.value === 'current_script' && !activeScript.value) {
    setError(new Error('请先选择当前剧本'));
    return;
  }
  await run(
    () => api.exportProject(currentProject.value!.id, exportScope.value, activeScript.value?.id),
    exportScope.value === 'current_script' ? '当前剧本素材包已导出' : '总剧本素材包已导出',
  );
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
        <h2>项目历史</h2>
        <button
          v-for="project in projects"
          :key="project.id"
          class="history-item"
          :class="{ active: currentProject?.id === project.id }"
          @click="loadProject(project.id)"
        >
          <strong>{{ project.title }}</strong>
          <small>{{ project.status }} · {{ project.script_count }} 剧本 · {{ project.entity_count }} 实体</small>
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
            <h2>项目剧本管理</h2>
          </div>
          <div class="toolbar">
            <button class="secondary" :disabled="!currentProject || loading" @click="addScript">加入当前项目</button>
            <button class="primary" :disabled="loading" @click="createProject">创建新项目</button>
          </div>
        </div>

        <div v-if="scripts.length" class="script-list">
          <button
            v-for="script in scripts"
            :key="script.id"
            class="script-item"
            :class="{ active: script.id === activeScript?.id }"
            @click="setActiveScript(script)"
          >
            <strong>{{ script.order_index }}. {{ script.title }}</strong>
            <small>{{ script.status }} · {{ script.word_count }} 字</small>
          </button>
        </div>

        <div class="form-grid">
          <label>
            项目标题
            <input v-model="form.title" placeholder="创建新项目时使用" />
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
          剧本标题
          <input v-model="form.script_title" placeholder="默认使用剧本前 24 个字" />
        </label>
        <label>
          剧本文字
          <textarea v-model="form.script" rows="14" />
        </label>
        <footer class="panel-footer">
          <span>{{ form.script.length }} 字 · 当前剧本：{{ activeScript?.title ?? '未选择' }}</span>
          <button class="secondary" :disabled="!activeScript || loading" @click="analyzeActiveScript">
            解析当前剧本并更新项目资产
          </button>
        </footer>
      </section>

      <section v-if="activeStep === 'graph'" class="panel">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 2</p>
            <h2>项目级知识图谱</h2>
          </div>
          <button class="primary" :disabled="!activeScript || loading" @click="analyzeActiveScript">解析当前剧本</button>
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
            <small>来源剧本数：{{ (selectedNode?.source_script_ids ?? graph.nodes[0].source_script_ids).length }}</small>
          </aside>
        </div>
        <div v-else class="empty">
          <p>还没有知识图谱。请先创建项目并解析当前剧本。</p>
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
              <span class="pill">{{ entity.status }} · {{ entity.source_script_count }} 剧本</span>
              <button class="secondary" @click="saveEntity(entity)">保存</button>
            </div>
          </article>
        </div>
      </section>

      <section v-if="activeStep === 'images'" class="panel image-step">
        <div class="panel-title">
          <div>
            <p class="eyebrow">Step 4</p>
            <h2>项目级实体模型参考图</h2>
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
              <small>{{ entity.type }} · {{ entity.images.length }} 张图 · {{ entity.source_script_count }} 剧本</small>
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
        <div class="scope-bar">
          <label><input v-model="frameScope" type="radio" value="current_script" /> 当前剧本</label>
          <label><input v-model="frameScope" type="radio" value="all_scripts" /> 总剧本</label>
          <span>{{ frameScope === 'current_script' ? activeScript?.title ?? '未选择当前剧本' : `${scripts.length} 个剧本` }}</span>
        </div>
        <div class="frame-list">
          <article v-for="frame in currentFrames" :key="frame.id" class="frame-card">
            <div class="frame-index">Frame {{ frame.frame_index }} · {{ frame.script_title }} · {{ frame.scope }}</div>
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
          <label><input v-model="exportScope" type="radio" value="current_script" /> 当前剧本</label>
          <label><input v-model="exportScope" type="radio" value="all_scripts" /> 总剧本</label>
          <span>导出结构：frames/001/scene.md + entities/实体图</span>
        </div>
        <div class="export-summary">
          <div><strong>{{ scripts.length }}</strong><span>项目剧本</span></div>
          <div><strong>{{ entities.length }}</strong><span>共享实体</span></div>
          <div><strong>{{ currentFrames.length }}</strong><span>当前范围帧</span></div>
        </div>
        <div class="export-list">
          <a v-for="item in exportsList" :key="item.id" :href="assetUrl(item.file_url)" download>
            下载 {{ item.scope }} 素材包 · {{ item.frame_count }} 帧 · {{ new Date(item.created_at).toLocaleString() }}
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
          <div class="metric"><span>当前剧本</span><strong>{{ activeScript?.title ?? '未选择' }}</strong></div>
          <div class="metric"><span>总剧本</span><strong>{{ currentProject.script_count }}</strong></div>
          <div class="metric"><span>实体</span><strong>{{ currentProject.entity_count }}</strong></div>
          <div class="metric"><span>已配图实体</span><strong>{{ currentProject.completed_entity_image_count }}</strong></div>
          <div class="metric"><span>分帧</span><strong>{{ currentProject.frame_count }}</strong></div>
        </template>
      </section>

      <section class="summary-card">
        <h2>下一步</h2>
        <p v-if="activeStep === 'script'">在项目中新增剧本，或切换当前剧本继续解析。</p>
        <p v-else-if="activeStep === 'graph'">检查当前剧本给项目图谱带来的新增节点和关系。</p>
        <p v-else-if="activeStep === 'entities'">维护项目级实体，实体图会被所有剧本共用。</p>
        <p v-else-if="activeStep === 'images'">为项目实体生成或上传主参考图。</p>
        <p v-else-if="activeStep === 'frames'">选择当前剧本或总剧本生成分帧。</p>
        <p v-else>选择导出范围，素材包会按数字帧目录组织。</p>
      </section>
    </aside>
  </div>
</template>
