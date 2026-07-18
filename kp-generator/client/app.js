/* ═══════════════════════════════════
   STATE
═══════════════════════════════════ */
const state = {
  sessionId:  null,
  clientName: '',
  manager:    '',
  phone:      '',
  fileId:     null,
};

const DEFAULT_TRUSTED =
  'АО «СУЭК», АК «АЛРОСА», ПАО «Русал», АО «Полюс», ' +
  'ГМК «Норильский никель», АО «Евраз», ПАО «НЛМК», ' +
  'АО «Металлоинвест», АО «Северсталь», АО «ММК»';

let blockIdCounter = 0;
function newId() { return `block_${++blockIdCounter}`; }

/* ═══════════════════════════════════
   UTILITIES
═══════════════════════════════════ */
function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showError(id, msg) { const el = document.getElementById(id); el.textContent = msg; el.hidden = false; }
function clearError(id) { document.getElementById(id).hidden = true; }

function setLoading(btnId, on) {
  const btn = document.getElementById(btnId);
  btn.classList.toggle('loading', on);
  btn.disabled = on;
}

/* ═══════════════════════════════════
   NAVIGATION
═══════════════════════════════════ */
function resetAndGoToStep1() {
  // Clear state
  state.sessionId  = null;
  state.clientName = '';
  state.manager    = '';
  state.phone      = '';
  state.fileId     = null;

  // Clear step 1 form
  document.getElementById('clientName').value   = '';
  document.getElementById('managerName').value  = '';
  document.getElementById('managerPhone').value = '';
  document.getElementById('manualText').value   = '';
  selectedFile = null;
  fileInput.value = '';
  fileChosen.hidden = true;
  clearError('step1Error');

  goToStep(1);
}

function goToStep(n) {
  [1, 2, 3].forEach(i => {
    document.getElementById(`step${i}`).hidden = i !== n;
    document.getElementById(`step${i}`).classList.toggle('active', i === n);
    document.getElementById(`ind-${i}`).classList.toggle('active', i === n);
    document.getElementById(`ind-${i}`).classList.toggle('done', i < n);
  });
  window.scrollTo(0, 0);
}

/* ═══════════════════════════════════
   STEP 1 — Upload
═══════════════════════════════════ */
const dropZone      = document.getElementById('dropZone');
const fileInput     = document.getElementById('fileInput');
const fileChosen    = document.getElementById('fileChosen');
const fileChosenName = document.getElementById('fileChosenName');

let selectedFile = null;

document.getElementById('browseBtn').addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => handleFileSelect(fileInput.files[0]));
dropZone.addEventListener('click', e => { if (e.target.id !== 'browseBtn') fileInput.click(); });
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.classList.remove('dragover'); handleFileSelect(e.dataTransfer.files[0]); });

function handleFileSelect(file) {
  if (!file) return;
  if (!/\.(pdf|docx|doc)$/i.test(file.name)) {
    showError('step1Error', 'Поддерживаются только файлы PDF и DOCX');
    return;
  }
  selectedFile = file;
  fileChosenName.textContent = file.name;
  fileChosen.hidden = false;
  document.getElementById('manualText').value = '';
  clearError('step1Error');
}

document.getElementById('fileClearBtn').addEventListener('click', () => {
  selectedFile = null;
  fileInput.value = '';
  fileChosen.hidden = true;
});

document.getElementById('extractBtn').addEventListener('click', async () => {
  clearError('step1Error');

  const clientName  = document.getElementById('clientName').value.trim();
  const manager     = document.getElementById('managerName').value.trim();
  const phone       = document.getElementById('managerPhone').value.trim();
  const manualText  = document.getElementById('manualText').value.trim();

  if (!clientName) return showError('step1Error', 'Укажите наименование клиента');
  if (!selectedFile && !manualText) return showError('step1Error', 'Загрузите файл или вставьте текст');

  state.clientName = clientName;
  state.manager    = manager;
  state.phone      = phone;

  setLoading('extractBtn', true);
  try {
    let resp;
    if (selectedFile) {
      const fd = new FormData();
      fd.append('file', selectedFile);
      fd.append('client', clientName);
      fd.append('manager', manager);
      fd.append('phone', phone);
      resp = await fetch('/api/extract', { method: 'POST', body: fd });
    } else {
      resp = await fetch('/api/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: manualText, client: clientName, manager, phone }),
      });
    }

    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'Ошибка извлечения');

    state.sessionId = data.data.sessionId;

    populateStep2(data.data);
    goToStep(2);
  } catch (err) {
    showError('step1Error', err.message);
  } finally {
    setLoading('extractBtn', false);
  }
});

/* ═══════════════════════════════════
   STEP 2 — Block constructor
═══════════════════════════════════ */
function populateStep2(data) {
  document.getElementById('e-name').value         = data.name         || '';
  document.getElementById('e-brand').value        = data.brand        || '';
  document.getElementById('e-warranty').value     = data.warranty     || '';
  document.getElementById('e-availability').value = data.availability || '';
  document.getElementById('e-price').value        = data.price        || '';

  const pt = Array.isArray(data.paymentTerms) ? data.paymentTerms.join('\n') : (data.paymentTerms || '');
  document.getElementById('e-paymentTerms').value = pt;
  document.getElementById('e-trustedBy').value    = DEFAULT_TRUSTED;

  const container = document.getElementById('blocksContainer');
  container.innerHTML = '';

  (data.blocks || []).forEach(block => {
    const el = createBlockElement({
      id:       block.id || newId(),
      type:     block.type || 'table',
      title:    block.title || '',
      rows:     block.rows || [],
      text:     block.text || '',
      imageRef: null,
    });
    container.appendChild(el);
  });
}

/* ── Snapshot DOM data into el._blockData (call before switching type) ── */
function snapshotBlockData(el) {
  const d = el._blockData;

  // Save title-block inner fields
  const titleInner = el.querySelector('.block-title-input-inner');
  if (titleInner) d.title = titleInner.value;
  const textLine = el.querySelector('.block-text-line');
  if (textLine) d.text = textLine.value;

  // Save rows from DOM (table and split blocks)
  const paramRows = el.querySelectorAll('.param-row');
  if (paramRows.length > 0) {
    d.rows = [];
    paramRows.forEach(row => {
      const isSec = row.dataset.section === '1';
      const p = row.querySelector('.p-name')?.value || '';
      const v = isSec ? null : (row.querySelector('.p-value')?.value ?? '');
      if (p || v !== null) d.rows.push([p, v]);
    });
  }

  // Save text from DOM if text block is currently visible
  const ta = el.querySelector('.block-text-area');
  if (ta) d.text = ta.value;
}

/* ── Build a block DOM element ── */
function createBlockElement(block) {
  const div = document.createElement('div');
  div.className = 'block-item';
  div.dataset.id = block.id;
  div.draggable = true;

  // Persistent data store — survives type switches
  div._blockData = {
    id:       block.id,
    type:     block.type || 'table',
    title:    block.title || '',
    rows:     block.rows  || [['', '']],
    text:     block.text  || '',
    imageRef: block.imageRef || null,
  };

  div.innerHTML = `
    <div class="block-header">
      <span class="drag-handle" title="Перетащить для изменения порядка">⠿</span>
      <input type="text" class="block-title-input" value="${esc(block.title)}" placeholder="Название блока" />
      <div class="type-tabs">
        <button class="type-tab ${block.type === 'title' ? 'active' : ''}" data-type="title">Обложка</button>
        <button class="type-tab ${block.type === 'split' ? 'active' : ''}" data-type="split">Фото+Хар-ки</button>
        <button class="type-tab ${block.type === 'photo' ? 'active' : ''}" data-type="photo">Фото</button>
        <button class="type-tab ${block.type === 'table' ? 'active' : ''}" data-type="table">Таблица</button>
        <button class="type-tab ${block.type === 'text'  ? 'active' : ''}" data-type="text">Текст</button>
      </div>
      <button class="btn-remove" title="Удалить блок">✕</button>
    </div>
    <div class="block-content" id="content-${block.id}">
      ${renderBlockContent(div._blockData)}
    </div>
  `;

  // Type tabs — save data before switching, restore on switch back
  div.querySelectorAll('.type-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const newType = btn.dataset.type;
      if (newType === div._blockData.type) return; // already active

      // 1. Save current DOM state
      snapshotBlockData(div);

      // 2. Switch type
      div._blockData.type = newType;
      div.querySelectorAll('.type-tab').forEach(b => b.classList.toggle('active', b === btn));

      // 3. Re-render with preserved data
      div.querySelector('.block-content').innerHTML = renderBlockContent(div._blockData);
    });
  });

  // Delete
  div.querySelector('.btn-remove').addEventListener('click', () => div.remove());

  addDragListeners(div);
  return div;
}

/* ── Helpers for split/table row rendering ── */
function renderParamRow(r) {
  // r[1] === null → section header; r[1] === '' → single-col; else two-col
  if (r[1] === null) {
    return `<div class="param-row split-section-row" data-section="1">
      <input type="text" class="p-name" value="${esc(r[0])}" placeholder="Название раздела" style="grid-column:1/3;font-weight:700;background:var(--dark);color:var(--yellow);border-color:var(--dark)" />
      <button class="btn-remove" onclick="this.closest('.param-row').remove()">✕</button>
    </div>`;
  }
  return `<div class="param-row">
    <input type="text" class="p-name" value="${esc(r[0])}" placeholder="Параметр" />
    <input type="text" class="p-value" value="${esc(r[1])}" placeholder="Значение (пусто = пункт списка)" />
    <button class="btn-remove" onclick="this.closest('.param-row').remove()">✕</button>
  </div>`;
}

/* ── Render block content based on type ── */
function renderBlockContent(block) {
  if (block.type === 'title') {
    return `
      <div style="display:flex;flex-direction:column;gap:10px">
        <div class="form-group" style="margin:0">
          <label style="font-size:12px;color:var(--muted)">Название техники (крупно на слайде)</label>
          <input type="text" class="block-title-input-inner" value="${esc(block.title)}" placeholder="Фронтальный погрузчик LW550RU" />
        </div>
        <div class="form-group" style="margin:0">
          <label style="font-size:12px;color:var(--muted)">Описание / комплектация (мелко под названием)</label>
          <input type="text" class="block-text-line" value="${esc(block.text || '')}" placeholder="Ковш 3.5 м³, джойстик, кондиционер" />
        </div>
        <div class="title-preview">🖼 Титульный слайд — название техники на тёмном фоне с логотипом Ремтехники</div>
      </div>`;
  }

  if (block.type === 'split') {
    const ref  = block.imageRef;
    const rows = block.rows && block.rows.length ? block.rows : [['Характеристики', null], ['', '']];
    const photoHtml = ref
      ? `<img src="/api/image/${ref.sessionId}/${ref.filename}" class="photo-preview" alt="Фото" />
         <div class="photo-actions" style="margin-top:6px;display:flex;align-items:center;gap:8px">
           <label class="btn-outline" style="cursor:pointer;font-size:12px">
             Заменить фото
             <input type="file" accept="image/*" hidden onchange="handlePhotoReplace(this)" />
           </label>
           <span class="photo-upload-status" style="font-size:11px;color:var(--muted)"></span>
         </div>`
      : `<label class="photo-drop-zone" style="min-height:140px">
           <div class="photo-drop-icon">📷</div>
           <div class="photo-drop-text" style="font-size:13px">Загрузить фото</div>
           <div class="photo-drop-hint">JPG или PNG</div>
           <input type="file" accept="image/*" hidden onchange="handlePhotoReplace(this)" />
           <span class="photo-upload-status" style="font-size:11px;color:var(--muted);margin-top:4px;display:block"></span>
         </label>`;

    return `
      <div class="split-block">
        <div class="split-photo">${photoHtml}</div>
        <div class="split-table-col">
          <div class="param-table">
            ${rows.map(r => renderParamRow(r)).join('')}
          </div>
          <div class="split-add-btns" style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn-add" onclick="addSplitSection(this)">+ раздел</button>
            <button class="btn-add" onclick="addSplitRow(this)">+ строку</button>
          </div>
        </div>
      </div>`;
  }

  if (block.type === 'photo') {
    const ref = block.imageRef;
    if (ref) {
      return `
        <div class="photo-block">
          <img src="/api/image/${ref.sessionId}/${ref.filename}" class="photo-preview" alt="Фото" />
          <div class="photo-actions" style="margin-top:8px;display:flex;align-items:center;gap:10px">
            <label class="btn-outline" style="cursor:pointer">
              Заменить фото
              <input type="file" accept="image/*" hidden onchange="handlePhotoReplace(this)" />
            </label>
            <span class="photo-upload-status" style="font-size:12px;color:var(--muted)"></span>
          </div>
        </div>`;
    }
    return `
      <div class="photo-block">
        <label class="photo-drop-zone">
          <div class="photo-drop-icon">📷</div>
          <div class="photo-drop-text">Нажмите чтобы загрузить фото техники</div>
          <div class="photo-drop-hint">JPG или PNG, до 20 МБ</div>
          <input type="file" accept="image/*" hidden onchange="handlePhotoReplace(this)" />
          <span class="photo-upload-status" style="font-size:12px;color:var(--muted);margin-top:6px;display:block"></span>
        </label>
      </div>`;
  }

  if (block.type === 'table') {
    const rows = block.rows && block.rows.length ? block.rows : [['', '']];
    return `
      <div class="param-table">
        ${rows.filter(r => r[1] !== null).map(r => `
          <div class="param-row">
            <input type="text" class="p-name" value="${esc(r[0])}" placeholder="Параметр" />
            <input type="text" class="p-value" value="${esc(r[1])}" placeholder="Значение" />
            <button class="btn-remove" onclick="this.closest('.param-row').remove()">✕</button>
          </div>`).join('')}
      </div>
      <button class="btn-add" style="margin-top:8px" onclick="addTableRow(this)">+ строку</button>`;
  }

  if (block.type === 'text') {
    return `<textarea class="block-text-area" rows="4" placeholder="Введите текст...">${esc(block.text || '')}</textarea>`;
  }

  return '';
}

/* ── Add table row ── */
window.addTableRow = function(btn) {
  const table = btn.previousElementSibling;
  const row = document.createElement('div');
  row.className = 'param-row';
  row.innerHTML = `
    <input type="text" class="p-name" placeholder="Параметр" />
    <input type="text" class="p-value" placeholder="Значение" />
    <button class="btn-remove" onclick="this.closest('.param-row').remove()">✕</button>`;
  table.appendChild(row);
};

/* ── Split block: add section header ── */
window.addSplitSection = function(btn) {
  const table = btn.closest('.split-table-col').querySelector('.param-table');
  const row = document.createElement('div');
  row.className = 'param-row split-section-row';
  row.dataset.section = '1';
  row.innerHTML = `
    <input type="text" class="p-name" placeholder="Название раздела" style="grid-column:1/3;font-weight:700;background:var(--dark);color:var(--yellow);border-color:var(--dark)" />
    <button class="btn-remove" onclick="this.closest('.param-row').remove()">✕</button>`;
  table.appendChild(row);
  row.querySelector('input').focus();
};

/* ── Split block: add data row ── */
window.addSplitRow = function(btn) {
  const table = btn.closest('.split-table-col').querySelector('.param-table');
  const row = document.createElement('div');
  row.className = 'param-row';
  row.innerHTML = `
    <input type="text" class="p-name" placeholder="Параметр" />
    <input type="text" class="p-value" placeholder="Значение (пусто = пункт списка)" />
    <button class="btn-remove" onclick="this.closest('.param-row').remove()">✕</button>`;
  table.appendChild(row);
  row.querySelector('input').focus();
};

/* ── Replace / upload photo ── */
window.handlePhotoReplace = function(input) {
  const file = input.files[0];
  if (!file) return;

  const blockItem    = input.closest('.block-item');
  const blockContent = input.closest('.block-content');
  // Works for both standalone photo block and split block photo zone
  const photoContainer = blockContent.querySelector('.split-photo') ||
                         blockContent.querySelector('.photo-block');

  const previewHtml = (src, small) => `
    <img class="photo-preview" src="${src}" alt="Фото" ${small ? 'style="max-height:180px"' : ''} />
    <div class="photo-actions" style="margin-top:6px;display:flex;align-items:center;gap:8px">
      <label class="btn-outline" style="cursor:pointer;font-size:12px">
        Заменить фото
        <input type="file" accept="image/*" hidden onchange="handlePhotoReplace(this)" />
      </label>
      <span class="photo-upload-status" style="font-size:12px;color:var(--muted)">Загружаю...</span>
    </div>`;

  const isSplit = !!blockContent.querySelector('.split-photo');

  // Show a local preview immediately, then swap to server-backed URL once uploaded
  const reader = new FileReader();
  reader.onload = (e) => {
    if (photoContainer) photoContainer.innerHTML = previewHtml(e.target.result, isSplit);
  };
  reader.readAsDataURL(file);

  // Upload to server — store a file reference (no base64 in JSON)
  const fd = new FormData();
  fd.append('photo', file);
  fd.append('sessionId', state.sessionId || '');

  fetch('/api/upload-photo', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        blockItem._blockData.imageRef = { sessionId: data.sessionId, filename: data.filename };
        if (!state.sessionId) state.sessionId = data.sessionId;
        // Switch preview src to server URL (avoids large inline data in DOM)
        const img = blockItem.querySelector('.photo-preview');
        if (img) img.src = `/api/image/${data.sessionId}/${data.filename}`;
        const status = blockItem.querySelector('.photo-upload-status');
        if (status) { status.textContent = '✓ Готово'; setTimeout(() => { if (status) status.textContent = ''; }, 2000); }
      } else {
        const status = blockItem.querySelector('.photo-upload-status');
        if (status) status.textContent = 'Ошибка загрузки';
      }
    })
    .catch(() => {
      const status = blockItem.querySelector('.photo-upload-status');
      if (status) status.textContent = 'Ошибка загрузки';
    });
};

/* ── Add blank block ── */
document.getElementById('addBlockBtn').addEventListener('click', () => {
  const block = { id: newId(), type: 'table', title: 'Новый блок', rows: [['', '']], text: '', imageRef: null };
  const el = createBlockElement(block);
  document.getElementById('blocksContainer').appendChild(el);
  el.querySelector('.block-title-input').focus();
});

/* ── Collect data from a block element ── */
function collectBlockData(el) {
  // Snapshot current DOM state into _blockData first
  snapshotBlockData(el);

  const d = el._blockData;
  // For title blocks, the machine name is in the inner input (not the header input)
  const titleInnerVal = el.querySelector('.block-title-input-inner');
  const headerTitle = el.querySelector('.block-title-input').value.trim();

  return {
    id:       el.dataset.id,
    type:     d.type,
    title:    titleInnerVal ? titleInnerVal.value.trim() : headerTitle,
    rows:     d.rows     || [],
    text:     d.text     || '',
    imageRef: d.imageRef || null,
  };
}

/* ── Collect ALL step 2 data ── */
function collectStep2Data() {
  const blocks = [];
  document.querySelectorAll('#blocksContainer .block-item').forEach(el => {
    blocks.push(collectBlockData(el));
  });

  return {
    name:         document.getElementById('e-name').value.trim(),
    brand:        document.getElementById('e-brand').value.trim(),
    warranty:     document.getElementById('e-warranty').value.trim(),
    availability: document.getElementById('e-availability').value.trim(),
    price:        document.getElementById('e-price').value.trim(),
    paymentTerms: document.getElementById('e-paymentTerms').value.split('\n').map(s => s.trim()).filter(Boolean),
    trustedBy:    document.getElementById('e-trustedBy').value.trim(),
    manager:      state.manager,
    phone:        state.phone,
    blocks,
  };
}

/* ── Generate ── */
document.getElementById('generateBtn').addEventListener('click', async () => {
  clearError('step2Error');
  const kpData = collectStep2Data();

  setLoading('generateBtn', true);
  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kpData, clientName: state.clientName }),
    });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'Ошибка генерации');

    state.fileId = data.fileId;
    showStep3(kpData);
    goToStep(3);
  } catch (err) {
    showError('step2Error', err.message);
  } finally {
    setLoading('generateBtn', false);
  }
});

/* ═══════════════════════════════════
   STEP 3 — Preview & Download
═══════════════════════════════════ */
function showStep3(kp) {
  const row = (label, val) => val ? `<div class="preview-row"><span class="preview-label">${esc(label)}</span><span class="preview-value">${esc(val)}</span></div>` : '';
  const sec = (label) => `<div class="preview-section">${esc(label)}</div>`;

  let html = '';
  html += row('Клиент',       state.clientName);
  html += row('Менеджер',     state.manager);
  html += row('Техника',      kp.name);
  html += row('Бренд',        kp.brand);
  html += sec('Слайды');
  kp.blocks.forEach((b, i) => {
    html += row(`${i + 1}. ${b.type === 'photo' ? 'Фото' : b.type === 'table' ? 'Таблица' : 'Текст'}`, b.title);
  });
  html += row(`${kp.blocks.length + 1}. Цена`, kp.price || '—');

  document.getElementById('previewBox').innerHTML = html;
  document.getElementById('downloadLink').href = `/api/download/${state.fileId}`;
}

/* ═══════════════════════════════════
   DRAG & DROP (block reorder)
═══════════════════════════════════ */
let dragSrc = null;

function addDragListeners(el) {
  el.addEventListener('dragstart', e => {
    dragSrc = el;
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => el.classList.add('dragging'), 0);
  });

  el.addEventListener('dragend', () => {
    el.classList.remove('dragging');
    document.querySelectorAll('.block-item').forEach(b => b.classList.remove('drag-over'));
    dragSrc = null;
  });

  el.addEventListener('dragover', e => {
    e.preventDefault();
    if (dragSrc && dragSrc !== el) el.classList.add('drag-over');
  });

  el.addEventListener('dragleave', () => el.classList.remove('drag-over'));

  el.addEventListener('drop', e => {
    e.preventDefault();
    el.classList.remove('drag-over');
    if (!dragSrc || dragSrc === el) return;

    const container = document.getElementById('blocksContainer');
    const items = [...container.querySelectorAll('.block-item')];
    const srcIdx = items.indexOf(dragSrc);
    const tgtIdx = items.indexOf(el);
    if (srcIdx < 0 || tgtIdx < 0) return;

    if (srcIdx < tgtIdx) el.after(dragSrc);
    else el.before(dragSrc);
  });
}
