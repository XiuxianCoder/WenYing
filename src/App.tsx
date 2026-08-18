import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  Copy,
  Download,
  Eye,
  FileText,
  FolderOpen,
  Globe2,
  ImagePlus,
  Inbox,
  KeyRound,
  LayoutDashboard,
  LayoutTemplate,
  Link2,
  LoaderCircle,
  MonitorUp,
  Palette,
  Radio,
  RefreshCw,
  Rocket,
  Save,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  WandSparkles,
  X,
} from "lucide-react";
import brandIcon from "../data/wenying-icon.png";

type Page = "source" | "design" | "templates" | "publish";

type Block = {
  index: number;
  type: string;
  text: string;
  level: number;
  imageId: string;
  rows: string[][];
};

type TemplateCard = {
  name: string;
  path: string;
  sourceType: string;
  primaryColor: string;
  accentColor: string;
};

type AppState = {
  ready: boolean;
  document: null | {
    title: string;
    blocks: Block[];
    blockCount: number;
    imageCount: number;
    placedImageCount: number;
    headings: string[];
  };
  template: {
    name: string;
    ready: boolean;
    sourceType: string;
    primaryColor: string;
    accentColor: string;
  };
  unmatchedImages: number;
  hasOutput: boolean;
  previewPath: string;
  previewHtml: string;
  existingHtmlPath: string;
  templates: TemplateCard[];
  styles: string[];
  targets: string[];
  settings: {
    endpoint: string;
    model: string;
    output_dir: string;
    ui_font: string;
    wechat_appid: string;
    wechat_author: string;
    apiKeyConfigured: boolean;
    wechatSecretConfigured: boolean;
  };
};

const EMPTY_STATE: AppState = {
  ready: false,
  document: null,
  template: { name: "未选择模板", ready: false, sourceType: "builtin", primaryColor: "#365b52", accentColor: "#a44b38" },
  unmatchedImages: 0,
  hasOutput: false,
  previewPath: "",
  previewHtml: "",
  existingHtmlPath: "",
  templates: [],
  styles: ["AI 智能匹配", "自然森系", "新中式雅韵", "高级黑金", "科技未来", "教育科普", "简约政务", "文化展览"],
  targets: ["自由网页 HTML", "135 编辑器代码", "秀米兼容代码", "微信公众号正文"],
  settings: {
    endpoint: "",
    model: "",
    output_dir: "",
    ui_font: "华文行楷",
    wechat_appid: "",
    wechat_author: "",
    apiKeyConfigured: false,
    wechatSecretConfigured: false,
  },
};

const STYLE_META: Record<string, { description: string; colors: string[] }> = {
  "AI 智能匹配": { description: "理解内容后自动决定视觉方向", colors: ["#2f5d50", "#d8a85f", "#f5f0e7"] },
  "自然森系": { description: "松石、苔绿与温柔纸张质感", colors: ["#375f50", "#9db7a3", "#ebe4d4"] },
  "新中式雅韵": { description: "克制留白与东方出版气质", colors: ["#284b46", "#a25345", "#eee6d5"] },
  "现代极简": { description: "清晰网格与现代杂志节奏", colors: ["#202624", "#8fa9a1", "#f7f7f4"] },
  "高级黑金": { description: "品牌感与沉稳人物专题", colors: ["#171918", "#b89556", "#ece4d2"] },
  "活动宣传": { description: "醒目信息层级与行动引导", colors: ["#2456a6", "#ef8b45", "#f5eddc"] },
  "节庆喜庆": { description: "热烈但不拥挤的红金设计", colors: ["#a83432", "#d8a544", "#fff3df"] },
  "青春活力": { description: "轻快撞色与社群活动感", colors: ["#5d67d8", "#ea6b91", "#ecf3ff"] },
  "科技未来": { description: "深蓝、霓虹与数据视觉", colors: ["#15284c", "#35c3c8", "#b5a7ff"] },
  "教育科普": { description: "知识层级清楚、重点友好", colors: ["#315b7d", "#e4a75b", "#eef4ef"] },
  "亲子童趣": { description: "柔和圆角与轻松阅读体验", colors: ["#ed8c71", "#61a7a0", "#fff2c9"] },
  "简约政务": { description: "端正、清晰、正式可靠", colors: ["#315b77", "#7993a4", "#edf2f4"] },
  "文化展览": { description: "画册式留白和精致图注", colors: ["#503e34", "#a87345", "#eee6da"] },
  "摄影画册": { description: "让大图成为文章的主角", colors: ["#1c1d1d", "#77736b", "#f1eee8"] },
};

const NAV_ITEMS = [
  { id: "source" as const, label: "创建原稿", icon: FileText },
  { id: "design" as const, label: "视觉设计", icon: Palette },
  { id: "templates" as const, label: "模板库", icon: LayoutTemplate },
  { id: "publish" as const, label: "输出发布", icon: Send },
];

function App() {
  const [state, setState] = useState<AppState>(EMPTY_STATE);
  const [page, setPage] = useState<Page>("source");
  const [busy, setBusy] = useState("");
  const [busySince, setBusySince] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [writerOpen, setWriterOpen] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [selectedStyle, setSelectedStyle] = useState("AI 智能匹配");
  const [seed, setSeed] = useState(() => Math.floor(100000 + Math.random() * 899999));
  const [optimizeText, setOptimizeText] = useState(false);
  const [target, setTarget] = useState("自由网页 HTML");
  const [templateUrl, setTemplateUrl] = useState("");
  const [templateScreenshots, setTemplateScreenshots] = useState<string[]>([]);
  const [previewScale, setPreviewScale] = useState<"desktop" | "phone">("desktop");

  useEffect(() => {
    refresh().catch((reason) => setError(String(reason)));
  }, []);

  useEffect(() => {
    if (!busySince) return;
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - busySince) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busySince]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 4200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  async function refresh() {
    const value = await window.wenying.invoke<AppState>("get-state");
    setState(value);
    if (value.targets.length && !value.targets.includes(target)) setTarget(value.targets[0]);
  }

  async function execute<T extends Partial<AppState> | Record<string, unknown>>(
    label: string,
    method: string,
    params: Record<string, unknown> = {},
    success = "操作完成",
  ): Promise<T | null> {
    if (busy) return null;
    setError("");
    setBusy(label);
    setBusySince(Date.now());
    setElapsed(0);
    try {
      const result = await window.wenying.invoke<T>(method, params);
      if (result && "ready" in result) setState(result as unknown as AppState);
      setNotice(success);
      return result;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return null;
    } finally {
      setBusy("");
      setBusySince(0);
    }
  }

  async function importWord() {
    const path = await window.wenying.dialog("word");
    if (typeof path !== "string") return;
    const result = await execute<AppState>("解析 Word 结构", "parse-word", { path }, "原稿已导入");
    if (result) setPage("source");
  }

  async function addImages() {
    const paths = await window.wenying.dialog("images");
    if (!Array.isArray(paths) || !paths.length) return;
    await execute<AppState>("整理正文图片", "add-images", { paths }, `已加入 ${paths.length} 张图片`);
  }

  async function generateOriginal() {
    const result = await execute<AppState>(
      "AI 正在理解文章并设计版式",
      "generate-original",
      { style: selectedStyle, seed, optimize_text: optimizeText },
      "原创排版已生成并保存",
    );
    if (result) setPage("publish");
  }

  async function chooseTemplate(card: TemplateCard) {
    const result = await execute<AppState>("载入本地模板", "select-template", { path: card.path }, `已选择“${card.name}”`);
    if (result) setPage("templates");
  }

  async function removeTemplate(card: TemplateCard) {
    if (!window.confirm(`确定删除本地模板“${card.name}”吗？`)) return;
    await execute<AppState>("删除模板", "delete-template", { path: card.path }, "模板已删除");
  }

  async function addTemplateScreenshots() {
    const paths = await window.wenying.dialog("template-images");
    if (Array.isArray(paths) && paths.length) setTemplateScreenshots((current) => [...current, ...paths]);
  }

  async function learnAndGenerate() {
    const result = await execute<AppState>(
      "学习模板并匹配文章结构",
      "learn-template",
      { url: templateUrl, screenshots: templateScreenshots },
      "模板已学习、保存并生成文章",
    );
    if (result) setPage("publish");
  }

  async function useSelectedTemplate() {
    const result = await execute<AppState>("理解文章并套用本地模板", "generate-from-template", {}, "模板排版已生成");
    if (result) setPage("publish");
  }

  async function copyAdapted() {
    const result = await execute<{ html: string; report: string[] }>("转换兼容代码", "adapt-current", { target }, `${target}已复制`);
    if (result) await window.wenying.copyText(result.html);
  }

  async function exportAdapted() {
    if (!state.document) return setError("请先创建原稿。");
    const suffix = target === "自由网页 HTML" ? "web" : target === "135 编辑器代码" ? "135" : target === "秀米兼容代码" ? "xiumi" : "wechat";
    const defaultPath = `${state.settings.output_dir}\\${state.document.title}_${suffix}.html`;
    const path = await window.wenying.dialog("save-html", { defaultPath });
    if (typeof path !== "string") return;
    const result = await execute<{ path: string }>("导出适配文件", "export-html", { target, path }, "HTML 已导出");
    if (result) window.wenying.revealPath(result.path);
  }

  async function loadExistingHtml() {
    const path = await window.wenying.dialog("html");
    if (typeof path !== "string") return;
    const result = await execute<AppState>("读取已有 HTML", "load-existing-html", { path }, "已有 HTML 已载入，可直接发布");
    if (result) setPage("publish");
  }

  const firstParagraph = useMemo(
    () => state.document?.blocks.find((block) => block.type === "paragraph" && block.text.trim())?.text.slice(0, 100) || "",
    [state.document],
  );

  return (
    <div className="app-shell">
      <div className="window-dragbar">
        <div className="drag-brand"><img src={brandIcon} alt="" /> 文映 WenYing</div>
      </div>

      <aside className="navigation-rail">
        <div className="brand-seal" aria-label="文映"><img src={brandIcon} alt="文映" /></div>
        <nav>
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={page === item.id ? "nav-item active" : "nav-item"} onClick={() => setPage(item.id)}>
                <Icon size={20} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <button className="nav-item settings-nav" onClick={() => setSettingsOpen(true)}>
          <Settings size={20} />
          <span>应用设置</span>
        </button>
      </aside>

      <SharedInkScene />

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">{NAV_ITEMS.find((item) => item.id === page)?.label}</p>
            <h1>{pageTitle(page)}</h1>
          </div>
          <div className="header-actions">
            <span className={state.settings.apiKeyConfigured ? "connection-chip ok" : "connection-chip"}>
              <span className="status-dot" />{state.settings.apiKeyConfigured ? state.settings.model || "模型已配置" : "待配置模型"}
            </span>
            <button className="icon-button" title="刷新" onClick={() => refresh()}><RefreshCw size={17} /></button>
          </div>
        </header>

        <div className="workspace-scroll">
          {page === "source" && (
            <SourcePage
              state={state}
              onImport={importWord}
              onImages={addImages}
              onWriter={() => setWriterOpen(true)}
              onContinue={() => setPage("design")}
            />
          )}
          {page === "design" && (
            <DesignPage
              state={state}
              selectedStyle={selectedStyle}
              setSelectedStyle={setSelectedStyle}
              seed={seed}
              setSeed={setSeed}
              optimize={optimizeText}
              setOptimize={setOptimizeText}
              onGenerate={generateOriginal}
            />
          )}
          {page === "templates" && (
            <TemplatesPage
              state={state}
              url={templateUrl}
              setUrl={setTemplateUrl}
              screenshots={templateScreenshots}
              onScreenshots={addTemplateScreenshots}
              clearScreenshots={() => setTemplateScreenshots([])}
              onLearn={learnAndGenerate}
              onChoose={chooseTemplate}
              onDelete={removeTemplate}
              onUse={useSelectedTemplate}
            />
          )}
          {page === "publish" && (
            <PublishPage
              state={state}
              target={target}
              setTarget={setTarget}
              onCopy={copyAdapted}
              onExport={exportAdapted}
              onOpen={() => state.previewPath && window.wenying.openPath(state.previewPath)}
              onExisting={loadExistingHtml}
              onWechat={() => setPublishOpen(true)}
            />
          )}
        </div>

        <footer className="status-bar">
          <div className="status-message">
            {busy ? <><LoaderCircle size={14} className="spin" />{busy} · {elapsed} 秒</> : notice ? <><Check size={14} />{notice}</> : <><span className="status-dot" />就绪</>}
          </div>
          {state.previewPath && <button onClick={() => window.wenying.revealPath(state.previewPath)}><FolderOpen size={13} /> 查看输出目录</button>}
        </footer>
      </main>

      <PreviewPane
        state={state}
        scale={previewScale}
        setScale={setPreviewScale}
        onGenerate={() => setPage(state.template.ready ? "templates" : "design")}
      />

      {busy && <BusyCurtain label={busy} elapsed={elapsed} />}
      {error && <ErrorToast message={error} onClose={() => setError("")} />}
      {settingsOpen && <SettingsModal state={state} onClose={() => setSettingsOpen(false)} onSaved={(next) => { setState(next); setSettingsOpen(false); setNotice("设置已保存"); }} />}
      {writerOpen && <WriterModal onClose={() => setWriterOpen(false)} onComplete={(next) => { setState(next); setWriterOpen(false); setNotice("AI 原稿已完成"); }} run={execute} />}
      {publishOpen && state.document && (
        <PublishModal
          state={state}
          defaultDigest={firstParagraph}
          onClose={() => setPublishOpen(false)}
          run={execute}
          onSettings={() => { setPublishOpen(false); setSettingsOpen(true); }}
        />
      )}
    </div>
  );
}

function pageTitle(page: Page) {
  return {
    source: "让内容先站稳，再谈风格",
    design: "为文章选择一套视觉语言",
    templates: "收藏喜欢的排版，随时复用",
    publish: "把最终作品送到该去的地方",
  }[page];
}

function SourcePage({ state, onImport, onImages, onWriter, onContinue }: { state: AppState; onImport: () => void; onImages: () => void; onWriter: () => void; onContinue: () => void }) {
  return (
    <div className="page-stack">
      <section className="intro-card">
        <div className="intro-copy">
          <span className="section-kicker"><Sparkles size={14} /> 两种起点，一条完整工作流</span>
          <h2>已有文章，或从一个想法开始</h2>
          <p>文映会保留原稿结构和图片，也可以搜索公开资料生成一篇新的可编辑文章。</p>
        </div>
        <div className="ink-orbit"><img src={brandIcon} alt="" /></div>
      </section>

      <div className="choice-grid">
        <article className="source-choice" role="button" tabIndex={0} aria-label="导入已有 Word" onClick={onImport} onKeyDown={(event) => activateCard(event, onImport)}>
          <div className="choice-icon jade"><Upload size={21} /></div>
          <div><h3>导入已有 Word</h3><p>读取标题、正文、表格与文档内图片，之后可继续补充外部配图。</p></div>
          <span className="primary-button">选择 Word <ChevronRight size={16} /></span>
        </article>
        <article className="source-choice featured" role="button" tabIndex={0} aria-label="开始 AI 联网写作" onClick={onWriter} onKeyDown={(event) => activateCard(event, onWriter)}>
          <div className="choice-icon cinnabar"><Globe2 size={21} /></div>
          <div><h3>AI 联网写作</h3><p>输入主题、文章侧重点与篇幅，检索公开资料后生成一篇完整原稿。</p></div>
          <span className="secondary-button">开始创作 <WandSparkles size={16} /></span>
        </article>
      </div>

      {state.document ? (
        <section className="document-card">
          <div className="document-heading">
            <div className="doc-emblem"><BookOpen size={22} /></div>
            <div className="doc-title"><span>当前原稿</span><h2>{state.document.title}</h2></div>
            <button className="ghost-button" onClick={onImages}><ImagePlus size={16} />添加配套图片</button>
          </div>
          <div className="metric-row">
            <Metric value={state.document.blockCount} label="内容块" />
            <Metric value={state.document.imageCount} label="全部图片" />
            <Metric value={state.document.placedImageCount} label="已定位" />
            <Metric value={state.unmatchedImages} label="待智能定位" warn={state.unmatchedImages > 0} />
          </div>
          <div className="outline-list">
            <div className="outline-label">文章结构</div>
            {state.document.blocks.slice(0, 9).map((block) => (
              <div className="outline-row" key={`${block.index}-${block.type}`}>
                <span className={`block-type ${block.type}`}>{blockLabel(block.type)}</span>
                <span>{block.text || (block.type === "image" ? `图片 ${block.imageId}` : block.type === "table" ? "表格" : "未命名内容")}</span>
              </div>
            ))}
            {state.document.blocks.length > 9 && <div className="outline-more">还有 {state.document.blocks.length - 9} 个内容块</div>}
          </div>
          <div className="card-footer"><span>下一步，为文章创建原创视觉，或使用已有模板。</span><button className="primary-button" onClick={onContinue}>继续设计 <ChevronRight size={16} /></button></div>
        </section>
      ) : (
        <section className="empty-document"><FileText size={28} /><h3>还没有原稿</h3><p>导入 Word 或使用 AI 写作后，文章结构会显示在这里。</p></section>
      )}
    </div>
  );
}

function activateCard(event: React.KeyboardEvent<HTMLElement>, action: () => void) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  action();
}

function SharedInkScene() {
  return <div className="shared-ink-scene" aria-hidden="true"><AnimatedInkLife /></div>;
}

function AnimatedInkLife() {
  return (
    <div className="animated-ink-layer" aria-hidden="true">
      <span className="cycle-sun" />
      <svg className="ink-life" viewBox="0 0 1000 1000" preserveAspectRatio="none">
        <g className="ink-bird flying-bird bird-a">
          <path className="bird-wing bird-wing-left" d="M4 3C-6-5-18-13-32-14C-25-5-16 4-3 9Z" />
          <path className="bird-wing bird-wing-right" d="M6 3C16-5 29-9 42-6C31 0 21 7 8 9Z" />
          <path className="bird-body" d="M-8 4C-2 0 7-2 15 0C20 0 23 3 22 6C18 9 9 9 1 8C-3 7-6 6-8 4Z" />
          <circle className="bird-head" cx="19" cy="2.5" r="4.2" />
          <path className="bird-beak" d="M22 1L34 3L22 5Z" />
          <path className="bird-tail" d="M-6 5L-18 12L-11 2Z" />
        </g>
        <g className="ink-bird flying-bird bird-b">
          <path className="bird-wing bird-wing-left" d="M4 3C-6-5-18-13-32-14C-25-5-16 4-3 9Z" />
          <path className="bird-wing bird-wing-right" d="M6 3C16-5 29-9 42-6C31 0 21 7 8 9Z" />
          <path className="bird-body" d="M-8 4C-2 0 7-2 15 0C20 0 23 3 22 6C18 9 9 9 1 8C-3 7-6 6-8 4Z" />
          <circle className="bird-head" cx="19" cy="2.5" r="4.2" />
          <path className="bird-beak" d="M22 1L34 3L22 5Z" />
          <path className="bird-tail" d="M-6 5L-18 12L-11 2Z" />
        </g>
        <g className="ink-bird flying-bird bird-c">
          <path className="bird-wing bird-wing-left" d="M4 3C-6-5-18-13-32-14C-25-5-16 4-3 9Z" />
          <path className="bird-wing bird-wing-right" d="M6 3C16-5 29-9 42-6C31 0 21 7 8 9Z" />
          <path className="bird-body" d="M-8 4C-2 0 7-2 15 0C20 0 23 3 22 6C18 9 9 9 1 8C-3 7-6 6-8 4Z" />
          <circle className="bird-head" cx="19" cy="2.5" r="4.2" />
          <path className="bird-beak" d="M22 1L34 3L22 5Z" />
          <path className="bird-tail" d="M-6 5L-18 12L-11 2Z" />
        </g>
        <g className="river-boat">
          <path className="boat-hull" d="M-34 3Q0 18 34 3Q25 18-25 18Z" />
          <path className="boat-rim" d="M-31 4Q0 11 31 4" />
          <path className="boat-person" d="M-4 2Q-2-10 3-11Q9-9 8 2M2-11V-19" />
          <path className="boat-paddle" d="M8-2L28 18" />
        </g>
      </svg>
    </div>
  );
}

function PreviewLandscape() {
  return (
    <div className="preview-landscape" aria-hidden="true">
      <div className="poem-inscription">
        <p><span>行到水穷处</span><span>坐看云起时</span></p>
        <small>唐 · 王维《终南别业》</small>
        <i>文映</i>
      </div>
    </div>
  );
}

function Metric({ value, label, warn = false }: { value: number; label: string; warn?: boolean }) {
  return <div className={warn ? "metric warn" : "metric"}><strong>{value}</strong><span>{label}</span></div>;
}

function blockLabel(type: string) {
  return ({ heading: "标题", paragraph: "正文", image: "图片", quote: "引用", table: "表格", code: "代码" } as Record<string, string>)[type] || type;
}

function DesignPage({ state, selectedStyle, setSelectedStyle, seed, setSeed, optimize, setOptimize, onGenerate }: {
  state: AppState; selectedStyle: string; setSelectedStyle: (value: string) => void; seed: number; setSeed: (value: number) => void; optimize: boolean; setOptimize: (value: boolean) => void; onGenerate: () => void;
}) {
  return (
    <div className="page-stack">
      <section className="section-header-card">
        <div><span className="section-kicker"><WandSparkles size={14} /> AI 原创排版</span><h2>内容不动，气质可以千变万化</h2><p>默认只改变视觉样式；开启正文优化后，AI 才会润色表达。</p></div>
        <button className="primary-button large" disabled={!state.document} onClick={onGenerate}><Sparkles size={17} />生成原创排版</button>
      </section>

      <section className="panel-card">
        <div className="panel-title"><div><h3>选择风格方向</h3><p>随机种子会让同一种风格产生不同设计。</p></div><span>{state.styles.length} 种方向</span></div>
        <div className="style-grid">
          {state.styles.map((style) => {
            const meta = STYLE_META[style] || STYLE_META["AI 智能匹配"];
            return (
              <button key={style} className={selectedStyle === style ? "style-card selected" : "style-card"} onClick={() => setSelectedStyle(style)}>
                <div className="style-swatches">{meta.colors.map((color) => <span key={color} style={{ background: color }} />)}</div>
                <strong>{style}</strong><small>{meta.description}</small>
                {selectedStyle === style && <span className="selected-mark"><Check size={12} /></span>}
              </button>
            );
          })}
        </div>
      </section>

      <section className="panel-card design-options">
        <div className="field-group"><label>随机种子</label><div className="seed-row"><input value={seed} type="number" onChange={(event) => setSeed(Number(event.target.value))} /><button className="ghost-button" onClick={() => setSeed(Math.floor(100000 + Math.random() * 899999))}><RefreshCw size={15} />换一个</button></div><small>保留种子可以复现相近的设计方向。</small></div>
        <label className="switch-row"><span><strong>使用 AI 优化正文</strong><small>可能调整措辞，但严格保留事实、数字和段落顺序。</small></span><input type="checkbox" checked={optimize} onChange={(event) => setOptimize(event.target.checked)} /><i /></label>
      </section>
    </div>
  );
}

function TemplatesPage({ state, url, setUrl, screenshots, onScreenshots, clearScreenshots, onLearn, onChoose, onDelete, onUse }: {
  state: AppState; url: string; setUrl: (value: string) => void; screenshots: string[]; onScreenshots: () => void; clearScreenshots: () => void; onLearn: () => void; onChoose: (card: TemplateCard) => void; onDelete: (card: TemplateCard) => void; onUse: () => void;
}) {
  return (
    <div className="page-stack">
      <section className="template-capture-card">
        <div className="capture-ornament"><Link2 size={24} /></div>
        <div className="capture-content"><span className="section-kicker">学习参考文章</span><h2>把喜欢的排版收藏成模板</h2><p>填写公众号文章链接，也可以补充关键页面截图，AI 会理解颜色、层级、固定装饰与内容槽位。</p>
          <div className="url-field"><Link2 size={16} /><input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://mp.weixin.qq.com/s/..." /></div>
          <div className="capture-actions"><button className="ghost-button" onClick={onScreenshots}><ImagePlus size={16} />添加模板截图</button>{screenshots.length > 0 && <button className="text-button" onClick={clearScreenshots}>{screenshots.length} 张 · 清除</button>}<button className="primary-button" disabled={!state.document} onClick={onLearn}><Sparkles size={16} />学习并生成</button></div>
        </div>
      </section>

      {state.template.ready && (
        <section className="selected-template-banner">
          <div className="template-sample" style={{ background: `linear-gradient(135deg, ${state.template.primaryColor}, ${state.template.accentColor})` }} />
          <div><span>当前模板</span><strong>{state.template.name}</strong></div>
          <button className="primary-button" disabled={!state.document} onClick={onUse}>使用模板生成 <ChevronRight size={16} /></button>
        </section>
      )}

      <section className="panel-card">
        <div className="panel-title"><div><h3>本地模板库</h3><p>学习过与原创生成的样式都会保存在本机。</p></div><span>{state.templates.length} 个模板</span></div>
        {state.templates.length ? <div className="template-grid">{state.templates.map((card) => (
          <article className={state.template.name === card.name && state.template.ready ? "template-card active" : "template-card"} key={card.path}>
            <button className="template-preview" onClick={() => onChoose(card)} style={{ background: `linear-gradient(145deg, ${card.primaryColor}, ${card.accentColor})` }}><span /><i /><b /></button>
            <div className="template-info"><div><strong>{card.name}</strong><small>{card.sourceType === "ai_original" ? "AI 原创" : "参考模板"}</small></div><button title="删除模板" onClick={() => onDelete(card)}><Trash2 size={15} /></button></div>
          </article>
        ))}</div> : <div className="empty-inline"><LayoutTemplate size={24} /><span>还没有本地模板，从上方学习一篇参考文章吧。</span></div>}
      </section>
    </div>
  );
}

function PublishPage({ state, target, setTarget, onCopy, onExport, onOpen, onExisting, onWechat }: {
  state: AppState; target: string; setTarget: (value: string) => void; onCopy: () => void; onExport: () => void; onOpen: () => void; onExisting: () => void; onWechat: () => void;
}) {
  return (
    <div className="page-stack">
      <section className="section-header-card publish-hero">
        <div><span className="section-kicker"><Rocket size={14} /> 输出与发布</span><h2>{state.hasOutput ? "作品已经准备好了" : "先生成排版，再选择去向"}</h2><p>{state.existingHtmlPath ? `当前使用已有文件：${state.existingHtmlPath.split(/[\\/]/).pop()}` : "自由网页保留完整效果，编辑器版本优先保证兼容性。"}</p></div>
        <button className="ghost-button" onClick={onExisting}><FolderOpen size={16} />选择已有 HTML</button>
      </section>

      <section className="panel-card">
        <div className="panel-title"><div><h3>输出目标</h3><p>同一篇内容，可以转换为不同平台需要的代码。</p></div></div>
        <div className="target-grid">
          {state.targets.map((item, index) => {
            const Icon = [MonitorUp, LayoutDashboard, LayoutTemplate, Send][index] || FileText;
            return <button key={item} className={target === item ? "target-card selected" : "target-card"} onClick={() => setTarget(item)}><Icon size={20} /><strong>{item}</strong><small>{targetDescription(item)}</small>{target === item && <Check size={14} />}</button>;
          })}
        </div>
        <div className="publish-actions"><button className="secondary-button" disabled={!state.hasOutput} onClick={onOpen}><Eye size={16} />浏览器预览</button><button className="ghost-button" disabled={!state.hasOutput} onClick={onCopy}><Copy size={16} />复制适配代码</button><button className="primary-button" disabled={!state.hasOutput} onClick={onExport}><Download size={16} />导出 HTML</button></div>
      </section>

      <section className="wechat-card">
        <div className="wechat-icon"><Send size={23} /></div>
        <div><span className="section-kicker">微信公众号</span><h3>预览、保存草稿或正式发布</h3><p>正文图片会自动上传为微信素材。建议先进入草稿箱检查移动端效果。</p></div>
        <div className="wechat-status"><span className={state.settings.wechatSecretConfigured ? "status-dot ok" : "status-dot"} />{state.settings.wechatSecretConfigured ? "接口已配置" : "待配置接口"}</div>
        <button className="primary-button" disabled={!state.hasOutput} onClick={onWechat}>进入发布 <ChevronRight size={16} /></button>
      </section>
    </div>
  );
}

function targetDescription(value: string) {
  if (value.startsWith("自由")) return "完整渐变、装饰与轻动画";
  if (value.startsWith("135")) return "适合导入 135 编辑器";
  if (value.startsWith("秀米")) return "清理不兼容网页样式";
  return "最严格的微信兼容规则";
}

function PreviewPane({ state, scale, setScale, onGenerate }: { state: AppState; scale: "desktop" | "phone"; setScale: (value: "desktop" | "phone") => void; onGenerate: () => void }) {
  return (
    <aside className="preview-pane">
      <header className="preview-header"><div><span>实时预览</span><strong>{state.document?.title || "等待原稿"}</strong></div><div className="preview-toggle"><button className={scale === "desktop" ? "active" : ""} onClick={() => setScale("desktop")}>桌面</button><button className={scale === "phone" ? "active" : ""} onClick={() => setScale("phone")}>手机</button></div></header>
      <div className={`preview-stage ${scale}`}>
        <PreviewLandscape />
        {state.previewHtml ? <iframe title="文章预览" sandbox="" srcDoc={state.previewHtml} /> : <div className="preview-empty"><div className="paper-stack"><span /><span /><img src={brandIcon} alt="" /></div><h3>排版会在这里出现</h3><p>{state.document ? "选择原创风格或本地模板，生成后即可实时查看。" : "先导入 Word，或者让 AI 帮你写一篇文章。"}</p>{state.document && <button className="ghost-button" onClick={onGenerate}>开始设计 <ChevronRight size={15} /></button>}</div>}
      </div>
      <footer className="preview-footer"><span>{state.template.ready ? `模板：${state.template.name}` : "尚未选择模板"}</span>{state.previewPath && <span>已自动保存</span>}</footer>
    </aside>
  );
}

function SettingsModal({ state, onClose, onSaved }: { state: AppState; onClose: () => void; onSaved: (value: AppState) => void }) {
  const [form, setForm] = useState({ ...state.settings, api_key: "", wechat_secret: "" });
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState("");
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));

  async function chooseOutput() {
    const path = await window.wenying.dialog("output-directory");
    if (typeof path === "string") update("output_dir", path);
  }

  async function save() {
    setSaving(true); setProblem("");
    try {
      const value = await window.wenying.invoke<AppState>("save-settings", form);
      onSaved(value);
    } catch (reason) {
      setProblem(reason instanceof Error ? reason.message : String(reason));
    } finally { setSaving(false); }
  }

  async function testWechat() {
    setSaving(true); setProblem("");
    try {
      if (form.wechat_secret || form.wechat_appid !== state.settings.wechat_appid) await window.wenying.invoke("save-settings", form);
      const result = await window.wenying.invoke<{ message: string }>("test-wechat");
      setProblem(result.message);
    } catch (reason) { setProblem(reason instanceof Error ? reason.message : String(reason)); }
    finally { setSaving(false); }
  }

  return <Modal title="模型与应用设置" subtitle="配置只保存在本机" onClose={onClose} wide>
    <div className="settings-columns">
      <section><div className="modal-section-title"><KeyRound size={17} /><div><strong>多模态模型</strong><span>兼容 OpenAI Chat Completions 接口</span></div></div>
        <Field label="API 地址"><input value={form.endpoint} onChange={(e) => update("endpoint", e.target.value)} placeholder="https://api.openai.com/v1" /></Field>
        <Field label="模型名称"><input value={form.model} onChange={(e) => update("model", e.target.value)} placeholder="模型 ID" /></Field>
        <Field label="API Key" hint={state.settings.apiKeyConfigured ? "密钥已保存；留空表示不修改" : "尚未配置密钥"}><input type="password" value={form.api_key} onChange={(e) => update("api_key", e.target.value)} placeholder={state.settings.apiKeyConfigured ? "••••••••••••" : "输入 API Key"} /></Field>
      </section>
      <section><div className="modal-section-title"><Send size={17} /><div><strong>微信公众号接口</strong><span>发布前建议先测试连接</span></div></div>
        <Field label="AppID"><input value={form.wechat_appid} onChange={(e) => update("wechat_appid", e.target.value)} placeholder="wx..." /></Field>
        <Field label="AppSecret" hint={state.settings.wechatSecretConfigured ? "AppSecret 已保存；留空表示不修改" : "尚未配置 AppSecret"}><input type="password" value={form.wechat_secret} onChange={(e) => update("wechat_secret", e.target.value)} placeholder={state.settings.wechatSecretConfigured ? "••••••••••••" : "输入 AppSecret"} /></Field>
        <Field label="默认作者"><input value={form.wechat_author} onChange={(e) => update("wechat_author", e.target.value)} /></Field>
        <button className="ghost-button test-button" onClick={testWechat} disabled={saving}><ShieldCheck size={15} />测试公众号连接</button>
      </section>
    </div>
    <div className="settings-bottom"><Field label="HTML 输出目录"><div className="path-field"><input value={form.output_dir} onChange={(e) => update("output_dir", e.target.value)} /><button onClick={chooseOutput}><FolderOpen size={15} /></button></div></Field><Field label="界面字体"><select value={form.ui_font} onChange={(e) => update("ui_font", e.target.value)}><option>华文行楷</option><option>楷体</option><option>微软雅黑</option></select></Field></div>
    {problem && <div className={problem.includes("成功") ? "inline-message success" : "inline-message"}>{problem}</div>}
    <div className="modal-actions"><button className="ghost-button" onClick={onClose}>取消</button><button className="primary-button" onClick={save} disabled={saving}>{saving ? <LoaderCircle size={15} className="spin" /> : <Save size={15} />}保存设置</button></div>
  </Modal>;
}

function WriterModal({ onClose, onComplete, run }: { onClose: () => void; onComplete: (value: AppState) => void; run: <T extends Partial<AppState> | Record<string, unknown>>(label: string, method: string, params?: Record<string, unknown>, success?: string) => Promise<T | null> }) {
  const [form, setForm] = useState({ topic: "", keywords: "", article_type: "资讯综述", length: "1500", focus: "自动判断", requirements: "", include_sources: true });
  const update = (key: string, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }));
  async function submit() {
    if (!form.topic.trim()) return;
    const result = await run<AppState>("AI 联网搜索并撰写文章", "research-write", { ...form, length: Number(form.length) }, "AI 原稿已生成");
    if (result) onComplete(result);
  }
  return <Modal title="AI 联网写作" subtitle="从公开资料到完整原稿" onClose={onClose} wide>
    <div className="writer-hero"><Globe2 size={22} /><div><strong>先检索，再写作</strong><span>AI 会整理公开网页资料，并按你的重点组织文章；生成结果仍建议人工核验。</span></div></div>
    <Field label="文章主题"><input autoFocus value={form.topic} onChange={(e) => update("topic", e.target.value)} placeholder="例如：多智能体协作如何改变现代办公" /></Field>
    <Field label="搜索关键词" hint="留空则直接使用文章主题"><input value={form.keywords} onChange={(e) => update("keywords", e.target.value)} placeholder="产品名、机构、技术关键词……" /></Field>
    <div className="field-grid three"><Field label="文章类型"><select value={form.article_type} onChange={(e) => update("article_type", e.target.value)}><option>资讯综述</option><option>技术教程</option><option>代码实战</option><option>行业分析</option><option>活动推文</option><option>品牌故事</option></select></Field><Field label="目标篇幅"><select value={form.length} onChange={(e) => update("length", e.target.value)}><option value="800">约 800 字</option><option value="1500">约 1500 字</option><option value="2500">约 2500 字</option><option value="4000">约 4000 字</option></select></Field><Field label="文章侧重点"><select value={form.focus} onChange={(e) => update("focus", e.target.value)}><option>自动判断</option><option>技术原理</option><option>代码使用实例</option><option>行业趋势</option><option>实用步骤</option><option>观点评论</option><option>活动信息</option></select></Field></div>
    <Field label="具体要求" hint="可写目标读者、语气、必须包含的信息或代码语言"><textarea rows={4} value={form.requirements} onChange={(e) => update("requirements", e.target.value)} placeholder="例如：面向有 Python 基础的开发者，包含完整可运行代码……" /></Field>
    <label className="check-row"><input type="checkbox" checked={form.include_sources} onChange={(e) => update("include_sources", e.target.checked)} /><span><strong>在文章末尾保留资料来源</strong><small>推荐开启，方便人工核验事实、日期与引用。</small></span></label>
    <div className="modal-actions"><button className="ghost-button" onClick={onClose}>取消</button><button className="primary-button large" disabled={!form.topic.trim()} onClick={submit}><Sparkles size={16} />开始联网写作</button></div>
  </Modal>;
}

function PublishModal({ state, defaultDigest, onClose, run, onSettings }: { state: AppState; defaultDigest: string; onClose: () => void; run: <T extends Partial<AppState> | Record<string, unknown>>(label: string, method: string, params?: Record<string, unknown>, success?: string) => Promise<T | null>; onSettings: () => void }) {
  const [form, setForm] = useState({ title: state.document?.title || "", author: state.settings.wechat_author, digest: defaultDigest, cover: "" });
  const update = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  async function cover() { const path = await window.wenying.dialog("cover"); if (typeof path === "string") update("cover", path); }
  async function preview() { const result = await run<{ path: string }>("生成微信草稿预览", "wechat-preview", form, "微信草稿预览已生成"); if (result) window.wenying.openPath(result.path); }
  async function publish(mode: "draft" | "publish" | "mass") {
    if (mode !== "draft" && !window.confirm(mode === "publish" ? "文章会立即提交正式发布，确定继续吗？" : "文章会尝试群发给全部关注用户并消耗群发额度，确定继续吗？")) return;
    const labels = { draft: "上传微信公众号草稿箱", publish: "上传并提交正式发布", mass: "上传并群发全部用户" };
    const result = await run<Record<string, unknown>>(labels[mode], "publish-wechat", { ...form, mode }, mode === "draft" ? "已保存到微信公众号草稿箱" : "微信发布任务已提交");
    if (result) onClose();
  }
  const configured = state.settings.wechatSecretConfigured && Boolean(state.settings.wechat_appid);
  return <Modal title="发布到微信公众号" subtitle={state.existingHtmlPath ? "使用已有 HTML，不会重新生成" : "使用当前排版结果"} onClose={onClose} wide>
    {!configured && <div className="warning-banner"><AlertTriangle size={18} /><div><strong>公众号接口尚未配置</strong><span>需要 AppID、AppSecret 和正确的接口 IP 白名单。</span></div><button onClick={onSettings}>前往设置</button></div>}
    <div className="field-grid two"><Field label="文章标题"><input value={form.title} onChange={(e) => update("title", e.target.value)} /></Field><Field label="作者"><input value={form.author} onChange={(e) => update("author", e.target.value)} /></Field></div>
    <Field label="摘要"><textarea rows={3} value={form.digest} onChange={(e) => update("digest", e.target.value)} /></Field>
    <Field label="封面图片" hint="不选择则使用正文第一张图"><div className="path-field"><input value={form.cover} readOnly placeholder="使用正文第一张图" /><button onClick={cover}><FolderOpen size={15} /></button></div></Field>
    <div className="publish-primary-grid"><button className="ghost-button tall" onClick={preview}><Eye size={17} /><span><strong>草稿预览</strong><small>只在本机生成兼容预览</small></span></button><button className="primary-button tall" disabled={!configured} onClick={() => publish("draft")}><Inbox size={17} /><span><strong>保存到草稿箱</strong><small>不会主动触达读者</small></span></button></div>
    <div className="risk-zone"><div><AlertTriangle size={16} /><span><strong>高风险操作</strong><small>可能触达读者并消耗发布额度，请先检查草稿。</small></span></div><div><button disabled={!configured} onClick={() => publish("publish")}><Rocket size={15} />直接发布</button><button className="danger" disabled={!configured} onClick={() => publish("mass")}><Radio size={15} />群发全部用户</button></div></div>
  </Modal>;
}

function Modal({ title, subtitle, onClose, children, wide = false }: { title: string; subtitle?: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className={wide ? "modal wide" : "modal"}><header><div><span>{subtitle}</span><h2>{title}</h2></div><button onClick={onClose}><X size={18} /></button></header><div className="modal-body">{children}</div></div></div>;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <label className="field"><span><strong>{label}</strong>{hint && <small>{hint}</small>}</span>{children}</label>;
}

function BusyCurtain({ label, elapsed }: { label: string; elapsed: number }) {
  const phase = elapsed < 8 ? "准备资料与文章结构" : elapsed < 25 ? "调用模型理解内容" : elapsed < 55 ? "设计视觉系统与图片位置" : "整理结果并生成 HTML";
  return <div className="busy-curtain"><div className="busy-card"><div className="busy-symbol"><img src={brandIcon} alt="" /><span /></div><span className="section-kicker">文映正在工作</span><h3>{label}</h3><p>{phase}</p><div className="progress-track"><i /></div><small>已用时 {elapsed} 秒，请保持应用开启</small></div></div>;
}

function ErrorToast({ message, onClose }: { message: string; onClose: () => void }) {
  return <div className="error-toast"><AlertTriangle size={18} /><div><strong>操作没有完成</strong><span>{message}</span></div><button onClick={onClose}><X size={15} /></button></div>;
}

export default App;
