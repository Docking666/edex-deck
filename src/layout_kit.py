# -*- coding: utf-8 -*-
"""
eDEX-UI 布局套件 —— 运行时注入的布局切换器。

设计依据（读 eDEX 自身 CSS 得出）：
  body          : display:flex; flex-direction:row; flex-wrap:wrap; justify-content:center
  #main_shell   : width:65%; height:60.3%; 且自带 width/height transition（原生支持缩放）
  #filesystem   : position:relative; width:43vw; height:30vh   <- 在 flex 流内
  #keyboard     : position:relative; width:55.5vw               <- 在 flex 流内
  #mod_column_* : position:absolute; width:17%; top:2.5vh       <- 脱离流

  43vw + 55.5vw = 98.5vw，正好排成一行 → 这就是「左下文件 + 右下键盘」的成因。

  重排布局的关键：只动那些「非 absolute」的元素（main_shell / filesystem / keyboard）
  改 width/height/position，两侧面板则改 left/right/top 或直接隐藏。
"""

LAYOUT_JS = r"""
(() => {
  const STYLE_ID = '__edex_layout_style';
  const CTL_ID   = '__edex_layout_ctl';
  const LS_KEY   = '__edex_layout_preset';

  const LAYOUTS = {
    default: {
      label: 'DEFAULT',
      hint: '原生：左系统 / 中终端 / 右网络 / 左下文件 / 右下键盘',
      css: ''
    },

    cockpit: {
      label: 'COCKPIT',
      hint: '监控台：面板全集中左栏，键盘与文件栏让位，终端吃满',
      css: `
        section#mod_column_left{
          left:0.555vh; top:2.5vh; width:18%;
          height:auto; max-height:none;
        }
        /* 两栏纵向拼接后总高会超过一屏。以前的做法是藏掉 GLOBE，
           但那会让用户以为模块坏了，而且插件开关也救不回来
           （子元素被通配选择器一起压住了）。改成让右栏自己滚动。*/
        section#mod_column_right{
          left:0.555vh; right:auto; width:18%;
          height:auto; max-height:52%;
          overflow-y:auto; overflow-x:hidden;
          align-items:flex-end;
        }
        section#mod_column_left > h3.title{ left:0.555vh; }
        section#mod_column_right > h3.title{ right:0.555vh; }
        section#keyboard{ display:none !important; }
        /* 文件栏在 cockpit 下无法正常渲染（父级尺寸一变，eDEX 的文件网格就不出内容），
           索性让位给终端 */
        section#filesystem{ display:none !important; }
        section#main_shell{
          width:79%; height:90%; margin-left:19%;
        }
      `
    },

    focus: {
      label: 'FOCUS',
      hint: '终端优先：隐藏两侧面板与键盘，文件栏保持原生尺寸留在左下',
      css: `
        section#mod_column_left,
        section#mod_column_right,
        section#keyboard{ display:none !important; }
        section#main_shell{
          width:96%; height:62%; margin-left:0;
        }
        /* 文件栏保持 eDEX 原生尺寸 ——
           动它的内部网格会把图标压没 */
        section#filesystem{
          width:96%; margin-right:0;
          position:relative; top:0; opacity:1 !important;
        }
        section#filesystem > h3.title{ width:96%; }
      `
    }
  };

  const ORDER = ['default', 'cockpit', 'focus'];

  /* 所有可控单元。id 取自实际 DOM dump（dom.json），不是猜的。
     预设管「布局怎么排」，模块开关管「哪些显示」，两者叠加生效。*/
  const MODULES = [
    { id: 'mod_clock',               label: 'CLOCK',    group: 'PANEL' },
    { id: 'mod_sysinfo',             label: 'SYSINFO',  group: 'PANEL' },
    { id: 'mod_hardwareInspector',   label: 'HW',       group: 'PANEL' },
    { id: 'mod_cpuinfo',             label: 'CPU',      group: 'PANEL' },
    { id: 'mod_ramwatcher',          label: 'RAM',      group: 'PANEL' },
    { id: 'mod_toplist',             label: 'PROC',     group: 'PANEL' },
    { id: 'mod_netstat',             label: 'NETSTAT',  group: 'PANEL' },
    { id: 'mod_globe',               label: 'GLOBE',    group: 'PANEL' },
    { id: 'mod_conninfo',            label: 'TRAFFIC',  group: 'PANEL' },
    { id: 'filesystem',              label: 'FILES',    group: 'DOCK'  },
    { id: 'keyboard',                label: 'KEYBOARD', group: 'DOCK'  }
  ];

  const MOD_STYLE_ID = '__edex_mod_style';
  const MOD_LS_KEY = '__edex_hidden_modules';

  function hiddenSet() {
    try {
      const raw = localStorage.getItem(MOD_LS_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return new Set(Array.isArray(arr) ? arr : []);
    } catch (e) { return new Set(); }
  }

  function saveHidden(set) {
    try { localStorage.setItem(MOD_LS_KEY, JSON.stringify(Array.from(set))); } catch (e) {}
  }

  /* 单独一个 <style>，必须排在布局 style 之后 ——
     两者都带 !important，靠「后者覆盖前者」来保证模块开关能推翻预设 */
  function applyModules() {
    const set = hiddenSet();
    let el = document.getElementById(MOD_STYLE_ID);
    if (!el) {
      el = document.createElement('style');
      el.id = MOD_STYLE_ID;
      document.head.appendChild(el);
    }
    /* 底部条：被搬到 dock 区的模块落在这里 */
    const DOCK_CSS = [
      '#__edex_dock_strip{',
      'width:96%;display:flex;flex-direction:row;flex-wrap:wrap;',
      'gap:1.2vh;align-items:flex-start;justify-content:center;',
      'margin:0.5vh auto 0 auto}',
      '#__edex_dock_strip > *{flex:0 0 auto;max-width:30%;min-width:15%}'
    ].join('');

    el.textContent = Array.from(set).map((id) => {
      return (MODULES.some((m) => m.id === id) ? '#' + id : '[id="' + id + '"]') +
             '{ display:none !important; }';
    }).join('\n') + '\n' + DOCK_CSS;
    return set;
  }

  function toggleModule(id) {
    const set = hiddenSet();
    if (set.has(id)) { set.delete(id); } else { set.add(id); }
    saveHidden(set);
    applyModules();
    paintModules();
    // 隐藏/显示会改变 main_shell 的位置，重新对齐嵌入视图
    setTimeout(syncView, 200);
    return id;
  }

  /* ---- 模块区域分配 ----
     模块不只能显隐，还能在左栏 / 右栏 / 底部条之间搬运。
     实现方式是真的移动 DOM —— 预设只负责排版，不负责决定"哪个模块属于哪一栏"。*/

  const AREA_LS_KEY = '__edex_mod_area';
  const DOCK_ID = '__edex_dock_strip';
  const AREA_ORDER = ['left', 'right', 'dock'];
  const AREA_LABEL = { left: 'L', right: 'R', dock: 'D' };
  const AREAS = { left: '#mod_column_left', right: '#mod_column_right' };

  const DEFAULT_AREA = {
    mod_clock: 'left', mod_sysinfo: 'left', mod_hardwareInspector: 'left',
    mod_cpuinfo: 'left', mod_ramwatcher: 'left', mod_toplist: 'left',
    mod_netstat: 'right', mod_globe: 'right', mod_conninfo: 'right'
  };

  function areaMap() {
    try {
      const m = JSON.parse(localStorage.getItem(AREA_LS_KEY) || '{}');
      return (m && typeof m === 'object') ? m : {};
    } catch (e) { return {}; }
  }

  function saveAreaMap(m) {
    try { localStorage.setItem(AREA_LS_KEY, JSON.stringify(m)); } catch (e) {}
  }

  function areaOf(id) {
    return areaMap()[id] || DEFAULT_AREA[id] || 'left';
  }

  function ensureDockStrip() {
    let el = document.getElementById(DOCK_ID);
    if (el) return el;
    el = document.createElement('div');
    el.id = DOCK_ID;
    /* 插在 #main_shell 之后 —— body 是 flex-wrap，它会独占一行，
       正好落在终端下方、文件栏上方。*/
    const shell = document.querySelector('#main_shell');
    if (shell && shell.parentNode) {
      shell.parentNode.insertBefore(el, shell.nextSibling);
    } else {
      document.body.appendChild(el);
    }
    return el;
  }

  function applyAreas() {
    const m = areaMap();
    MODULES.forEach(function (mod) {
      if (mod.group === 'DOCK') return;   // filesystem / keyboard 是原生组件，不参与搬运
      const el = document.getElementById(mod.id);
      if (!el) return;
      const target = m[mod.id] || DEFAULT_AREA[mod.id] || 'left';
      const container = (target === 'dock')
        ? ensureDockStrip()
        : document.querySelector(AREAS[target]);
      if (container && el.parentNode !== container) container.appendChild(el);
    });

    /* 模块被搬空的栏位不必占着位置 —— 只剩一个标题空挂着很怪 */
    ['#mod_column_left', '#mod_column_right'].forEach(function (sel) {
      const col = document.querySelector(sel);
      if (!col) return;
      const hasMod = Array.prototype.some.call(col.children, function (c) {
        return c.tagName !== 'H3';
      });
      col.style.display = hasMod ? '' : 'none';
    });

    const strip = document.getElementById(DOCK_ID);
    if (strip) {
      const has = strip.children.length > 0;
      strip.style.display = has ? 'flex' : 'none';
      /* 终端要给底部条让位 —— 否则 dock 条落在视口外，搬过去的模块看不见。
         高度按 dock 条实际占用算，不写死百分比。*/
      const shell = document.querySelector('#main_shell');
      if (shell) {
        const preset = activePreset();
        if (preset === 'cockpit' || preset === 'focus') {
          const base = (preset === 'cockpit') ? 90 : 62;
          shell.style.height = has
            ? 'calc(' + base + '% - ' + (strip.offsetHeight + 10) + 'px)'
            : '';
        }
      }
    }
    return 'applied';
  }

  function cycleArea(id) {
    const cur = areaOf(id);
    const next = AREA_ORDER[(AREA_ORDER.indexOf(cur) + 1) % AREA_ORDER.length];
    const m = areaMap();
    m[id] = next;
    saveAreaMap(m);
    applyAreas();
    paintAreas();
    setTimeout(syncView, 260);
    return next;
  }

  function paintAreas() {
    const ctl = document.getElementById(CTL_ID);
    if (!ctl) return;
    ctl.querySelectorAll('[data-area]').forEach(function (b) {
      b.textContent = AREA_LABEL[areaOf(b.getAttribute('data-area'))] || '?';
    });
  }

  function paintModules() {
    const ctl = document.getElementById(CTL_ID);
    if (!ctl) return;
    const set = hiddenSet();
    ctl.querySelectorAll('[data-mod]').forEach((b) => {
      const id = b.getAttribute('data-mod');
      const off = set.has(id);
      b.style.opacity = off ? '0.38' : '1';
      b.style.borderColor = off
        ? 'rgba(131,131,143,0.35)'
        : 'rgba(var(--color_r),var(--color_g),var(--color_b),0.7)';
      b.style.background = off
        ? 'transparent'
        : 'rgba(var(--color_r),var(--color_g),var(--color_b),0.14)';
    });
  }

  function applyStyle(css) {
    let el = document.getElementById(STYLE_ID);
    if (!el) {
      el = document.createElement('style');
      el.id = STYLE_ID;
      document.head.appendChild(el);
    }
    el.textContent = css || '';
  }

  function activePreset() {
    try {
      const v = localStorage.getItem(LS_KEY);
      return LAYOUTS[v] ? v : 'default';
    } catch (e) { return 'default'; }
  }

  /* 布局一变，#main_shell 的尺寸就变，嵌进去的 BrowserView 必须重新对齐，
     否则中央的 Web UI 会错位。*/
  function syncView() {
    const v = globalThis.__edexView;
    if (!v) return 'no-view';
    const el = document.querySelector('#main_shell');
    if (!el) return 'no-shell';
    const r = el.getBoundingClientRect();
    try {
      v.setBounds({
        x: Math.round(r.x), y: Math.round(r.y),
        width: Math.round(r.width), height: Math.round(r.height)
      });
      return 'ok';
    } catch (e) { return 'err:' + e.message; }
  }

  /* 布局一变 #main_shell 的尺寸就变，嵌进去的 BrowserView 必须跟着走。
     早先靠 setTimeout 猜过渡时长，不可靠 —— 用户切 tab、拉窗口、
     任何一次重排都会让尺寸漂移，表现就是"点一下别的地方才对上"。
     改成直接监听元素尺寸变化。*/
  function watchShellSize() {
    const el = document.querySelector('#main_shell');
    if (!el) return 'no-shell';
    if (!globalThis.ResizeObserver) return 'no-resizeobserver';
    if (globalThis.__edexDeckRO) return 'already';
    let t = null;
    globalThis.__edexDeckRO = new ResizeObserver(function () {
      if (t) clearTimeout(t);
      t = setTimeout(syncView, 50);
    });
    globalThis.__edexDeckRO.observe(el);
    return 'observing';
  }

  /* 两个 column 的高度都由内容撑开，无法用固定 top 拼接 ——
     必须测出左栏实际底边，再把右栏放到它下面。*/
  function applyDynamic(name) {
    const L = document.querySelector('#mod_column_left');
    const R = document.querySelector('#mod_column_right');
    if (!L || !R) return;
    L.style.height = '';
    R.style.height = '';
    R.style.top = '';
    if (name === 'cockpit') {
      L.style.height = 'auto';
      R.style.height = 'auto';
      positionRightColumn();
    }
  }

  /* 把右栏放到左栏正下方。
     光靠延时测量不可靠 —— CSS 改完浏览器是异步重排的，固定 140ms 拿到的
     可能还是旧高度，表现就是右栏贴在顶部。先等两帧再测。*/
  function positionRightColumn() {
    const L = document.querySelector('#mod_column_left');
    const R = document.querySelector('#mod_column_right');
    if (!L || !R) return 'no-columns';
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        setTimeout(function () {
          try {
            /* 留 4px 间隙；高度按剩余空间算，否则右栏底部会被视口切掉 */
            const bottom = Math.round(L.getBoundingClientRect().bottom);
            const avail = window.innerHeight - bottom - 14;
            R.style.top = (bottom + 4) + 'px';
            R.style.maxHeight = Math.max(120, avail) + 'px';
          } catch (e) {}
        }, 40);
      });
    });
    return 'ok';
  }

  /* 左栏高度会随模块增删变化（用户把模块搬进搬出），持续跟随 */
  function watchColumnHeights() {
    const L = document.querySelector('#mod_column_left');
    if (!L || !globalThis.ResizeObserver) return 'no';
    if (globalThis.__edexDeckColRO) return 'already';
    globalThis.__edexDeckColRO = new ResizeObserver(function () {
      if (activePreset() !== 'cockpit') return;
      positionRightColumn();
    });
    globalThis.__edexDeckColRO.observe(L);
    return 'observing';
  }

  function setPreset(name) {
    if (!LAYOUTS[name]) name = 'default';
    applyStyle(LAYOUTS[name].css);
    applyDynamic(name);
    try { localStorage.setItem(LS_KEY, name); } catch (e) {}
    const ctl = document.getElementById(CTL_ID);
    if (ctl) {
      ctl.querySelectorAll('[data-layout]').forEach((b) => {
        const on = b.getAttribute('data-layout') === name;
        b.style.background = on ? 'rgb(var(--color_r),var(--color_g),var(--color_b))' : 'transparent';
        b.style.color = on ? 'var(--color_light_black)' : 'rgb(var(--color_r),var(--color_g),var(--color_b))';
        b.style.opacity = on ? '1' : '0.65';
      });
      const h = ctl.querySelector('.__elc_hint');
      if (h) h.textContent = LAYOUTS[name].hint;
    }
    /* 布局切换带来两类变化，只靠一种机制覆盖不全：
       - 尺寸变化       -> ResizeObserver 会捕获
       - 位置变化       -> 如 COCKPIT 给 #main_shell 加 margin-left，
                           尺寸可能没变，ResizeObserver 根本不触发
       所以再按过渡时长补几个时间点，把"只是挪了位置"的情况也兜住。*/
    [120, 300, 620, 1100].forEach(function (ms) {
      setTimeout(syncView, ms);
    });
    return name;
  }

  /* ---- 悬浮窗拖拽 / 贴边吸附隐藏 ---- */
  const POS_KEY = '__edex_ctl_pos';
  const PIN_LS_KEY = '__edex_ctl_pin';
  const EDGE_LS_KEY = '__edex_ctl_edge';
  const PIN_STYLE_ID = '__edex_pin_style';
  const SNAP_DIST = 40;   // 距屏幕边多近算「贴边」
  const PEEK_PX = 9;      // 收起后留在屏幕内的触发条宽度

  const PIN_CSS = [
    '#__edex_layout_ctl{transition:transform .28s cubic-bezier(.4,0,.2,1)}',
    '#__edex_layout_ctl.pk-left{transform:translateX(calc(-100% + ' + PEEK_PX + 'px))}',
    '#__edex_layout_ctl.pk-right{transform:translateX(calc(100% - ' + PEEK_PX + 'px))}',
    '#__edex_layout_ctl.pk-top{transform:translateY(calc(-100% + ' + PEEK_PX + 'px))}',
    '#__edex_layout_ctl.pk-bottom{transform:translateY(calc(100% - ' + PEEK_PX + 'px))}',
    '#__edex_layout_ctl.pk-open{transform:translateX(0) translateY(0)}'
  ].join('\n');

  function ensurePinStyle() {
    if (document.getElementById(PIN_STYLE_ID)) return;
    const s = document.createElement('style');
    s.id = PIN_STYLE_ID;
    s.textContent = PIN_CSS;
    document.head.appendChild(s);
  }

  function isPinned() {
    try { return localStorage.getItem(PIN_LS_KEY) === '1'; } catch (e) { return false; }
  }
  function setPinned(v) {
    try { localStorage.setItem(PIN_LS_KEY, v ? '1' : '0'); } catch (e) {}
  }
  function savedEdge() {
    try { return localStorage.getItem(EDGE_LS_KEY) || ''; } catch (e) { return ''; }
  }
  function saveEdge(e) {
    try {
      if (e) { localStorage.setItem(EDGE_LS_KEY, e); } else { localStorage.removeItem(EDGE_LS_KEY); }
    } catch (err) {}
  }

  function savePos(wrap) {
    try {
      localStorage.setItem(POS_KEY, JSON.stringify({
        left: wrap.style.left, top: wrap.style.top
      }));
    } catch (e) {}
  }

  function resetPos(wrap) {
    wrap.style.left = 'auto';
    wrap.style.top = 'auto';
    wrap.style.right = '1.1vh';
    wrap.style.bottom = '1.1vh';
    try { localStorage.removeItem(POS_KEY); } catch (e) {}
  }

  function restorePos(wrap) {
    try {
      const p = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
      if (p && p.left && p.top && p.left !== 'auto') {
        wrap.style.left = p.left;
        wrap.style.top = p.top;
        wrap.style.right = 'auto';
        wrap.style.bottom = 'auto';
      }
    } catch (e) {}
  }

  function snapEdgeOf(wrap) {
    if (!isPinned()) return '';
    const r = wrap.getBoundingClientRect();
    const W = window.innerWidth, H = window.innerHeight;
    if (r.left < SNAP_DIST) return 'left';
    if (W - r.right < SNAP_DIST) return 'right';
    if (r.top < SNAP_DIST) return 'top';
    if (H - r.bottom < SNAP_DIST) return 'bottom';
    return '';
  }

  function applyPeek(wrap, edge, open) {
    ['left', 'right', 'top', 'bottom'].forEach((e) => wrap.classList.remove('pk-' + e));
    wrap.classList.remove('pk-open');
    if (edge) {
      wrap.classList.add('pk-' + edge);
      if (open) wrap.classList.add('pk-open');
    }
  }

  function paintPin() {
    const ctl = document.getElementById(CTL_ID);
    if (!ctl) return;
    const b = ctl.querySelector('[data-pin]');
    if (!b) return;
    const on = isPinned();
    b.style.background = on
      ? 'rgba(var(--color_r),var(--color_g),var(--color_b),0.16)' : 'transparent';
    b.style.opacity = on ? '1' : '0.6';
  }

  function makeDraggable(wrap) {
    let sx = 0, sy = 0, ox = 0, oy = 0;
    let dragging = false, moved = false;
    let hoverTimer = null, lockUntil = 0;
    const THRESHOLD = 4;

    wrap.style.cursor = 'move';

    const expand = () => {
      if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
      const edge = savedEdge();
      if (!edge) return;
      lockUntil = Date.now() + 450;
      applyPeek(wrap, edge, true);
    };

    const collapse = () => {
      const edge = savedEdge();
      if (!edge) return;
      if (Date.now() < lockUntil) return;
      hoverTimer = setTimeout(() => {
        applyPeek(wrap, edge, false);
        hoverTimer = null;
      }, 320);
    };

    wrap.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      const r = wrap.getBoundingClientRect();
      sx = e.clientX; sy = e.clientY;
      ox = r.left; oy = r.top;
      dragging = true; moved = false;
      if (savedEdge()) applyPeek(wrap, savedEdge(), true);
      e.preventDefault();
    });

    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const dx = e.clientX - sx, dy = e.clientY - sy;
      if (!moved && Math.abs(dx) < THRESHOLD && Math.abs(dy) < THRESHOLD) return;
      moved = true;
      const w = wrap.offsetWidth, h = wrap.offsetHeight;
      const nx = Math.max(0, Math.min(window.innerWidth - w, ox + dx));
      const ny = Math.max(0, Math.min(window.innerHeight - h, oy + dy));
      wrap.style.left = nx + 'px';
      wrap.style.top = ny + 'px';
      wrap.style.right = 'auto';
      wrap.style.bottom = 'auto';
    });

    window.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      if (!moved) return;
      savePos(wrap);
      const edge = snapEdgeOf(wrap);
      saveEdge(edge);
      if (edge) {
        lockUntil = Date.now() + 950;
        applyPeek(wrap, edge, true);
        setTimeout(() => {
          applyPeek(wrap, savedEdge(), false);
        }, 950);
      } else {
        applyPeek(wrap, '', false);
      }
      paintPin();
    });

    wrap.addEventListener('mouseenter', expand);
    wrap.addEventListener('mouseover', expand);
    /* 兜底：收起态只剩几像素露在屏幕内，个别环境下 mouseenter 不触发，
       用 mousemove 补上（expand 内部有 clearTimeout，重复调用开销可忽略）*/
    wrap.addEventListener('mousemove', expand);
    wrap.addEventListener('mouseleave', collapse);

    wrap.addEventListener('click', (e) => {
      if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; }
    }, true);

    /* 双击 = 取消吸附 + 复位到右下角 */
    wrap.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      saveEdge('');
      applyPeek(wrap, '', false);
      resetPos(wrap);
      paintPin();
    });
  }

  function buildControl() {
    if (document.getElementById(CTL_ID)) return;
    const wrap = document.createElement('div');
    wrap.id = CTL_ID;
    wrap.style.cssText = [
      'position:fixed', 'right:1.1vh', 'bottom:1.1vh', 'z-index:2147483000',
      'display:flex', 'flex-direction:column', 'align-items:flex-end', 'gap:0.5vh',
      'font-family:var(--font_main,sans-serif)', 'font-size:1.35vh',
      'letter-spacing:0.12vh', 'user-select:none'
    ].join(';');

    const hint = document.createElement('div');
    hint.className = '__elc_hint';
    hint.style.cssText = [
      'max-width:34vw', 'text-align:right', 'line-height:1.5',
      'color:#83838F', 'font-size:1.2vh', 'opacity:0.9',
      'text-shadow:0 0 4px rgba(0,0,0,.9)', 'pointer-events:none'
    ].join(';');

    const pill = (text) => {
      const b = document.createElement('div');
      b.textContent = text;
      b.style.cssText = [
        'cursor:pointer', 'padding:0.42vh 0.85vh', 'border-radius:0.3vh',
        'border:0.1vh solid rgba(var(--color_r),var(--color_g),var(--color_b),0.55)',
        'background:transparent',
        'color:rgb(var(--color_r),var(--color_g),var(--color_b))',
        'transition:background .18s,color .18s,opacity .18s,border-color .18s',
        'white-space:nowrap'
      ].join(';');
      return b;
    };

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:0.5vh;align-items:center';

    const title = document.createElement('div');
    title.textContent = 'LAYOUT';
    title.style.cssText = 'color:#83838F;font-size:1.2vh;margin-right:0.4vh;letter-spacing:0.16vh;pointer-events:none';
    row.appendChild(title);

    ORDER.forEach((name) => {
      const b = pill(LAYOUTS[name].label);
      b.setAttribute('data-layout', name);
      b.addEventListener('click', (e) => { e.stopPropagation(); setPreset(name); });
      row.appendChild(b);
    });

    const gap = document.createElement('div');
    gap.style.cssText = 'width:0.6vh';
    row.appendChild(gap);

    const modsBtn = pill('MODULES');
    modsBtn.id = '__edex_mods_btn';
    row.appendChild(modsBtn);

    /* PIN = 贴边自动隐藏。开启后拖到屏幕边缘松手即吸附，悬停弹出 */
    const pinBtn = pill('PIN');
    pinBtn.setAttribute('data-pin', '1');
    pinBtn.title = '贴边自动隐藏（拖到屏幕边缘松手吸附，鼠标悬停弹出；双击控件取消）';
    pinBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const ctl = document.getElementById(CTL_ID);
      setPinned(!isPinned());
      if (!ctl) { paintPin(); return; }
      if (isPinned()) {
        const edge = snapEdgeOf(ctl);
        saveEdge(edge);
        if (edge) {
          applyPeek(ctl, edge, true);
          setTimeout(() => applyPeek(ctl, savedEdge(), false), 700);
        }
      } else {
        saveEdge('');
        applyPeek(ctl, '', false);
      }
      paintPin();
    });
    row.appendChild(pinBtn);

    /* ---- 模块开关面板 ---- */
    const mods = document.createElement('div');
    mods.id = '__edex_mods_panel';
    mods.style.cssText = [
      'display:none', 'flex-direction:column', 'gap:0.55vh', 'align-items:flex-end',
      'padding:0.8vh 1vh', 'border-radius:0.4vh',
      'border:0.1vh solid rgba(var(--color_r),var(--color_g),var(--color_b),0.3)',
      'background:rgba(0,0,0,0.72)', 'backdrop-filter:blur(3px)'
    ].join(';');

    ['PANEL', 'DOCK'].forEach((grp) => {
      const g = document.createElement('div');
      g.style.cssText = 'display:flex;gap:0.45vh;align-items:center;flex-wrap:wrap;justify-content:flex-end';

      const lab = document.createElement('div');
      lab.textContent = grp;
      lab.style.cssText = 'color:#83838F;font-size:1.1vh;margin-right:0.3vh;letter-spacing:0.14vh;pointer-events:none';
      g.appendChild(lab);

      MODULES.filter((m) => m.group === grp).forEach((m) => {
        const b = pill('');
        b.setAttribute('data-mod', m.id);
        b.style.padding = '0.34vh 0.66vh';
        b.style.fontSize = '1.15vh';
        b.style.display = 'inline-flex';
        b.style.alignItems = 'center';
        b.style.gap = '0.45vh';

        const name = document.createElement('span');
        name.textContent = m.label;
        b.appendChild(name);

        /* 只有侧栏模块能搬运；FILES / KEYBOARD 是 eDEX 原生组件 */
        if (m.group === 'PANEL') {
          const badge = document.createElement('span');
          badge.setAttribute('data-area', m.id);
          badge.textContent = AREA_LABEL[areaOf(m.id)];
          badge.title = 'L 左栏 / R 右栏 / D 底部条 —— 点击切换';
          badge.style.cssText = [
            'cursor:pointer', 'padding:0 0.32vh', 'border-radius:0.2vh',
            'font-size:1.0vh', 'line-height:1.55',
            'border:0.08vh solid rgba(var(--color_r),var(--color_g),var(--color_b),0.5)',
            'opacity:0.85'
          ].join(';');
          badge.addEventListener('click', function (ev) {
            ev.stopPropagation();
            cycleArea(m.id);
          });
          b.appendChild(badge);
        }

        b.addEventListener('click', (e) => { e.stopPropagation(); toggleModule(m.id); });
        g.appendChild(b);
      });
      mods.appendChild(g);
    });

    modsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = mods.style.display === 'flex';
      mods.style.display = open ? 'none' : 'flex';
      modsBtn.style.background = open
        ? 'transparent'
        : 'rgba(var(--color_r),var(--color_g),var(--color_b),0.16)';
    });

    wrap.appendChild(hint);
    wrap.appendChild(row);
    wrap.appendChild(mods);
    document.body.appendChild(wrap);

    restorePos(wrap);
    makeDraggable(wrap);
  }

  buildControl();
  ensurePinStyle();
  applyModules();
  const now = setPreset(activePreset());
  applyAreas();
  paintModules();
  paintPin();
  paintAreas();
  watchShellSize();
  watchColumnHeights();

  /* 恢复上次的贴边吸附状态（收起态） */
  (function () {
    const ctl = document.getElementById(CTL_ID);
    const edge = savedEdge();
    if (ctl && edge) applyPeek(ctl, edge, false);
  })();

  return JSON.stringify({
    ok: true,
    preset: now,
    presets: ORDER,
    moduleCount: MODULES.length,
    hidden: Array.from(hiddenSet()),
    pinned: isPinned(),
    edge: savedEdge(),
    hasShell: !!document.querySelector('#main_shell'),
    hasFs: !!document.querySelector('#filesystem'),
    hasKb: !!document.querySelector('#keyboard'),
    hasColL: !!document.querySelector('#mod_column_left'),
    hasColR: !!document.querySelector('#mod_column_right')
  });
})()
"""


def set_preset_js(name):
    """生成「切换到指定预设」的注入脚本（供脚本化截图用）。"""
    return (
        "(()=>{const b=document.querySelector('#__edex_layout_ctl [data-layout=\"%s\"]');"
        "if(!b)return 'no-control';b.click();return 'clicked:%s';})()" % (name, name)
    )
