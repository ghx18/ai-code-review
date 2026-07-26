/**
 * AI Code Review — Frontend App
 */
let pollTimer = null;

// ── Tab ──

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.remove('bg-white', 'dark:bg-gray-700', 'text-gray-900', 'dark:text-white', 'shadow-sm');
    b.classList.add('text-gray-500', 'dark:text-gray-400');
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));

  const map = { new: 0, history: 1, stats: 2 };
  const btns = document.querySelectorAll('.tab-btn');
  btns[map[name]].classList.remove('text-gray-500', 'dark:text-gray-400');
  btns[map[name]].classList.add('bg-white', 'dark:bg-gray-700', 'text-gray-900', 'dark:text-white', 'shadow-sm');
  document.getElementById('panel' + name.charAt(0).toUpperCase() + name.slice(1)).classList.remove('hidden');

  if (name === 'history') loadHistory();
  if (name === 'stats') loadStats();
}

// ── Dark Mode ──

document.getElementById('darkToggle').addEventListener('click', () => {
  document.documentElement.classList.toggle('dark');
  localStorage.setItem('dark', document.documentElement.classList.contains('dark'));
});
if (localStorage.getItem('dark') === 'true' || (!localStorage.getItem('dark') && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
  document.documentElement.classList.add('dark');
}

// ── Submit ──

async function submitReview(e) {
  e.preventDefault();
  const code = document.getElementById('inputCode').value.trim();
  const btn = document.getElementById('submitBtn');

  if (!code) { alert('请粘贴代码或拖放文件'); return; }

  // Reset
  document.getElementById('resultArea').classList.remove('hidden');
  document.getElementById('progressBar').classList.remove('hidden');
  document.getElementById('resultCard').classList.add('hidden');

  btn.disabled = true;
  setProgress(5, '正在提交审查...');

  try {
    const resp = await fetch('/api/review/code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, language: 'python', filename: 'code.py' })
    });
    const data = await resp.json();
    setProgress(100, '审查完成');
    setTimeout(() => showResult(data), 300);
  } catch (err) {
    setProgress(0, '提交失败: ' + err.message);
    btn.disabled = false;
  }
}

// ── Show Result ──

function showResult(data) {
  document.getElementById('progressBar').classList.add('hidden');
  document.getElementById('resultCard').classList.remove('hidden');
  document.getElementById('submitBtn').disabled = false;

  if (!data || data.status === 'failed') {
    document.getElementById('resultSummary').textContent = '❌ 审查失败: ' + (data?.error || '未知错误');
    return;
  }

  const stats = data.stats || {};
  const total = stats.total || 0;

  document.getElementById('resultSummary').textContent = data.summary || `共发现 ${total} 个问题`;
  document.getElementById('badgeFiles').textContent = '📁 ' + (data.total_files || 0) + ' 个文件';
  document.getElementById('badgeTime').textContent = '⏱ ' + (data.elapsed_seconds || 0) + 's';

  // 严重度
  const severityMap = [
    { key: 'critical', label: '严重', cls: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300' },
    { key: 'major', label: '主要', cls: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300' },
    { key: 'minor', label: '次要', cls: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300' },
    { key: 'info', label: '建议', cls: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300' },
  ];
  document.getElementById('severityStats').innerHTML = severityMap.map(s =>
    `<div class="flex-1 text-center py-2 px-3 rounded-lg ${s.cls}"><span class="text-lg font-bold">${stats[s.key] || 0}</span><span class="text-xs ml-1">${s.label}</span></div>`
  ).join('');

  // 报告（Markdown → HTML）
  const reportEl = document.getElementById('reportContent');
  if (data.report) {
    reportEl.innerHTML = marked.parse(data.report);
  } else {
    reportEl.textContent = '（无详细报告）';
  }
}

// ── Progress ──

function setProgress(pct, msg) {
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressText').textContent = msg || '处理中...';
}

// ── History ──

async function loadHistory() {
  const el = document.getElementById('historyList');
  el.innerHTML = '<div class="text-center py-8 text-gray-400 text-sm">加载中...</div>';
  try {
    const resp = await fetch('/api/reviews?limit=50');
    const data = await resp.json();
    if (!data.reviews || data.reviews.length === 0) {
      el.innerHTML = '<div class="text-center py-8 text-gray-400 text-sm">暂无审查记录</div>';
      return;
    }
    el.innerHTML = data.reviews.map(r => {
      const s = r.stats || {};
      const total = s.total || 0;
      const sev = total > 0 ? `<span class="text-xs ${total > 10 ? 'text-red-500' : 'text-orange-400'}">${total} issues</span>` : '';
      const icon = r.status === 'completed' ? '✅' : '❌';
      return `<div class="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer transition-colors">
        <div class="flex items-center gap-3 min-w-0">
          <span>${icon}</span>
          <span class="text-sm font-medium text-gray-900 dark:text-white">#${r.id}</span>
          <span class="text-sm text-gray-500">${r.input_type}</span>
          <span class="text-xs text-gray-400 font-mono">${r.input_path || ''}</span>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          ${sev}
          <span class="text-xs text-gray-400">${r.elapsed_seconds ? r.elapsed_seconds.toFixed(1) + 's' : '-'}</span>
          <span class="text-xs text-gray-400">${r.created_at ? r.created_at.slice(0, 10) : ''}</span>
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    el.innerHTML = '<div class="text-center py-8 text-red-400 text-sm">加载失败</div>';
  }
}

// ── Stats ──

async function loadStats() {
  try {
    const resp = await fetch('/api/stats');
    const data = await resp.json();
    document.getElementById('statTotal').textContent = data.total_reviews || 0;
    document.getElementById('statCompleted').textContent = data.completed || 0;
    document.getElementById('statIssues').textContent = data.total_issues_found || 0;
  } catch {}
}

// ── Health ──

async function checkHealth() {
  const dot = document.querySelector('#statusDot span:first-child');
  try {
    const r = await fetch('/health');
    if (r.ok) {
      dot.className = 'w-2 h-2 rounded-full bg-green-400';
    }
  } catch {}
}

checkHealth();
setInterval(checkHealth, 30000);
