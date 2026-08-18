const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

class PythonBridge {
  constructor(projectRoot, packagedRoot, dataRoot) {
    this.projectRoot = projectRoot;
    this.packagedRoot = packagedRoot;
    this.dataRoot = dataRoot || projectRoot;
    this.process = null;
    this.pending = new Map();
    this.sequence = 0;
    this.stderr = [];
  }

  pythonCandidates() {
    const values = [
      process.env.WENYING_PYTHON,
      path.join(this.projectRoot, ".venv", "Scripts", "python.exe"),
      path.join(this.projectRoot, "venv", "Scripts", "python.exe"),
      "python",
      "py",
    ];
    return values.filter(Boolean);
  }

  resolvePython() {
    for (const candidate of this.pythonCandidates()) {
      if (candidate === "python" || candidate === "py" || fs.existsSync(candidate)) return candidate;
    }
    return "python";
  }

  bridgePath() {
    if (this.packagedRoot) return path.join(this.packagedRoot, "python", "wenying_bridge.py");
    return path.join(this.projectRoot, "wenying_bridge.py");
  }

  start() {
    if (this.process && !this.process.killed) return;
    const executable = this.resolvePython();
    const args = executable === "py" ? ["-3", "-u", this.bridgePath()] : ["-u", this.bridgePath()];
    this.process = spawn(executable, args, {
      cwd: this.packagedRoot ? path.join(this.packagedRoot, "python") : this.projectRoot,
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
        WENYING_PROJECT_ROOT: this.projectRoot,
        WENYING_DATA_ROOT: this.dataRoot,
      },
      stdio: ["pipe", "pipe", "pipe"],
    });

    const lines = readline.createInterface({ input: this.process.stdout });
    lines.on("line", (line) => {
      if (!line.trim()) return;
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        this.recordError(`无法解析 Python 返回：${line.slice(0, 500)}`);
        return;
      }
      const task = this.pending.get(message.id);
      if (!task) return;
      this.pending.delete(message.id);
      if (message.ok) task.resolve(message.result);
      else task.reject(new Error(message.error || "Python 服务执行失败"));
    });

    this.process.stderr.on("data", (chunk) => this.recordError(chunk.toString("utf8")));
    this.process.on("error", (error) => this.failAll(`无法启动 Python 服务：${error.message}`));
    this.process.on("exit", (code) => {
      this.failAll(`Python 服务已退出（代码 ${code ?? "未知"}）`);
      this.process = null;
    });
  }

  recordError(value) {
    const text = String(value || "").trim();
    if (!text) return;
    this.stderr.push(text);
    if (this.stderr.length > 80) this.stderr.shift();
    console.error("[WenYing Python]", text);
  }

  failAll(message) {
    for (const task of this.pending.values()) task.reject(new Error(message));
    this.pending.clear();
  }

  invoke(method, params = {}) {
    this.start();
    const id = ++this.sequence;
    const request = JSON.stringify({ id, method, params }) + "\n";
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.process.stdin.write(request, "utf8", (error) => {
        if (!error) return;
        this.pending.delete(id);
        reject(error);
      });
    });
  }

  stop() {
    if (this.process && !this.process.killed) this.process.kill();
    this.process = null;
  }
}

module.exports = { PythonBridge };
