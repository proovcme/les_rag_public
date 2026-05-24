import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { PCA } from './pca.js';

// Application State
let state = {
    qdrantUrl: 'http://localhost:6333',
    collections: [],
    currentCollection: '',
    points: [],            // Raw points with payload & vectors
    baseProjectedPoints: [], // PCA coordinates before visual spreading
    projectedPoints: [],   // N x 3 PCA coordinates
    selectedPointId: null,
    searchQuery: '',
    selectedFiles: new Set(),
    snapshotUrl: '',
    language: 'ru',        // Default UI language
    
    // Visualization Settings
    nodeSize: 1.0,
    glowIntensity: 0.7,
    showGrid: true,
    showConstellation: true,
    constellationNeighbors: 2, // number of neighbors to connect
    autoRotate: true,
    spreadStrength: 2.2,
    documentSpread: 1.4,
};

// Three.js Core Variables
let scene, camera, renderer, controls;
let instancedMesh;
let glowMesh;
let constellationLines;
let selectedDocumentMesh;
let gridHelper;
let starField;
let ambientLight, directionalLight, pointLight;
let requestId = null;
const LES_QDRANT_URL = (() => {
    const host = window.location.hostname || '127.0.0.1';
    return `http://${host}:6333`;
})();
const LES_COLLECTION_PRIORITY = ['les_rag_qwen3_06b', 'les_rag'];

// Hover & Raycasting
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let hoveredInstanceId = null;
let selectedInstanceId = null;
let initialInstancePositions = []; // for transition animation
let targetInstancePositions = [];  // for transition animation
let transitionProgress = 1.0;      // 0.0 to 1.0
const transitionSpeed = 0.02;

// Colors
const COLOR_NORMAL = new THREE.Color('#00f0ff');   // Cyan
const COLOR_MATCH = new THREE.Color('#05ffc0');    // Neon Green
const COLOR_DIM = new THREE.Color('#101c38');      // Deep Blue/Grey
const COLOR_CONTEXT = new THREE.Color('#17304f');  // Muted context blue
const COLOR_HOVER = new THREE.Color('#ff007f');    // Magenta
const COLOR_SELECT = new THREE.Color('#ffffff');   // White
const FILE_HIGHLIGHT_COLORS = [
    '#ff2f92',
    '#ffe15a',
    '#6dff8f',
    '#8f7cff',
    '#ff9f43',
    '#4df7ff',
    '#ff5f5f',
    '#b6ff3d',
];

// DOM Elements
const elements = {
    loader: document.getElementById('loader-overlay'),
    loaderStatus: document.getElementById('loader-status'),
    loaderConsole: document.getElementById('loader-console'),
    loadLesBtn: document.getElementById('load-les-btn'),
    loadSnapshotBtn: document.getElementById('load-snapshot-btn'),
    snapshotDownload: document.getElementById('snapshot-download'),
    totalPoints: document.getElementById('total-points'),
    vectorDim: document.getElementById('vector-dim'),
    pcaStatus: document.getElementById('pca-status'),
    
    // Sliders
    nodeSizeSlider: document.getElementById('node-size'),
    nodeSizeVal: document.getElementById('node-size-val'),
    glowSlider: document.getElementById('glow-intensity'),
    glowVal: document.getElementById('glow-intensity-val'),
    neighborsSlider: document.getElementById('constellation-neighbors'),
    neighborsVal: document.getElementById('neighbors-val'),
    spreadSlider: document.getElementById('spread-strength'),
    spreadVal: document.getElementById('spread-val'),
    docSpreadSlider: document.getElementById('doc-spread-strength'),
    docSpreadVal: document.getElementById('doc-spread-val'),
    
    // Toggles
    toggleGrid: document.getElementById('toggle-grid'),
    toggleConstellation: document.getElementById('toggle-constellation'),
    toggleRotate: document.getElementById('toggle-rotate'),
    
    // Search & Sidebar
    searchInput: document.getElementById('search-input'),
    fileFilterList: document.getElementById('file-filter-list'),
    detailPanel: document.getElementById('detail-panel'),
    closeDetailBtn: document.getElementById('close-detail'),
    helpToggleBtn: document.getElementById('help-toggle'),
    instructionsBar: document.getElementById('instructions-bar'),
    
    // Metadata fields
    metaId: document.getElementById('meta-id'),
    metaFile: document.getElementById('meta-file'),
    metaDocId: document.getElementById('meta-docid'),
    metaCoords: document.getElementById('meta-coords'),
    metaText: document.getElementById('meta-text'),
};

// ----------------------------------------------------
// LOCALIZATION (RU / EN) SYSTEM
// ----------------------------------------------------
const TRANSLATIONS = {
    ru: {
        "doc-title": "3D Визуализатор Базы Знаний Qdrant",
        "app-title": "Qdrant 3D Визуализатор",
        "section-conn": "Данные Л.Е.С.",
        "load-les-btn": "Обновить из Qdrant",
        "snapshot-download": "Скачать слепок data.js",
        "load-snapshot-btn": "Загрузить слепок data.js",
        "source-note": "Источник: локальный Qdrant Л.Е.С. · загрузка только по кнопке",
        "waiting-connection": "(Ожидание подключения...)",
        "section-stats": "Статистика коллекции",
        "stat-points": "Векторных точек",
        "stat-dims": "Размерность",
        "stat-pca-label": "Статус PCA:",
        "section-search": "Поиск по контенту",
        "search-placeholder": "Поиск текста или документа...",
        "section-tuning": "Визуальная настройка",
        "tune-scale": "Масштаб точек",
        "tune-glow": "Яркость свечения",
        "tune-constellation": "Связи созвездия",
        "tune-spread": "Разлипание точек",
        "tune-doc-spread": "Разнос документов",
        "section-toggles": "Отображение",
        "toggle-grid": "Сетка на полу",
        "toggle-constellation": "Линии созвездия",
        "toggle-rotate": "Вращение камеры",
        "section-isolate": "Подсветка документов",
        "inspect-title": "Инспекция точки",
        "inspect-subtitle": "Данные выбранного вектора",
        "inspect-uuid": "UUID точки",
        "inspect-file": "Исходный документ",
        "inspect-dochash": "Хэш / ID документа",
        "inspect-coords": "3D координаты (PCA)",
        "inspect-payload": "Текст чанка (Payload)",
        "inspect-default-text": "Выберите точку на графике, чтобы просмотреть её смысловое текстовое содержимое...",
        "inspect-empty-text": "(Пустой фрагмент текста)",
        "inspect-encrypted-text": "[ЗАШИФРОВАННЫЙ БЛОК ДАННЫХ BASE64]",
        "help-rotate-key": "ЛКМ + Перетаскивание",
        "help-rotate-val": "Вращение сцены",
        "help-zoom-key": "Колесо мыши",
        "help-zoom-val": "Масштаб",
        "help-pan-key": "ПКМ + Перетаскивание",
        "help-pan-val": "Панорама",
        "help-inspect-key": "Клик по точке",
        "help-inspect-val": "Инспекция точки",
        "loader-title": "3D Нейровизуализатор",
        "loader-note": "Загрузка данных запускается только вручную.",
        "toast-connect-fail": "Не удалось подключиться к Qdrant по адресу",
        "no-collections": "(Коллекции не найдены)",
        "no-file-metadata": "Метаданные о файлах отсутствуют",
        "no-file-name": "(Нет имени файла)"
    },
    en: {
        "doc-title": "Qdrant 3D Vector Space Visualizer",
        "app-title": "Qdrant 3D Visualizer",
        "section-conn": "LES Data",
        "load-les-btn": "Refresh from Qdrant",
        "snapshot-download": "Download data.js snapshot",
        "load-snapshot-btn": "Load data.js snapshot",
        "source-note": "Source: local LES Qdrant · loads only after button click",
        "waiting-connection": "(Waiting for connection...)",
        "section-stats": "Collection Stats",
        "stat-points": "Vector Points",
        "stat-dims": "Dimensions",
        "stat-pca-label": "PCA Status:",
        "section-search": "Payload Search",
        "search-placeholder": "Search text or document...",
        "section-tuning": "Visual Tuning",
        "tune-scale": "Node Scale",
        "tune-glow": "Glow Intensity",
        "tune-constellation": "Constellation Degree",
        "tune-spread": "Point Spread",
        "tune-doc-spread": "Document Spread",
        "section-toggles": "Toggles",
        "toggle-grid": "Show Grid floor",
        "toggle-constellation": "Show Constellation links",
        "toggle-rotate": "Auto Orbit Camera",
        "section-isolate": "Document Highlight",
        "inspect-title": "Point Inspection",
        "inspect-subtitle": "Selected Vector Dimensions Data",
        "inspect-uuid": "Point UUID",
        "inspect-file": "Source Document",
        "inspect-dochash": "Doc Hash / ID",
        "inspect-coords": "3D Space Coordinates (PCA)",
        "inspect-payload": "Vector Payload Text",
        "inspect-default-text": "Select a node from the scatter plot to inspect its semantic payload text chunk...",
        "inspect-empty-text": "(Empty snippet text)",
        "inspect-encrypted-text": "[ENCRYPTED/BASE64 DATA BLOB]",
        "help-rotate-key": "Left Click + Drag",
        "help-rotate-val": "Rotate Scene",
        "help-zoom-key": "Scroll",
        "help-zoom-val": "Zoom",
        "help-pan-key": "Right Click + Drag",
        "help-pan-val": "Pan",
        "help-inspect-key": "Left Click Node",
        "help-inspect-val": "Inspect Point",
        "loader-title": "3D Neural Visualizer",
        "loader-note": "Data loading starts only after button click.",
        "toast-connect-fail": "Failed to connect to Qdrant at",
        "no-collections": "(No collections found)",
        "no-file-metadata": "No file metadata available",
        "no-file-name": "(No file metadata)"
    }
};

const STATUS_TRANSLATIONS = {
    ru: {
        "CONNECTING...": "ПОДКЛЮЧЕНИЕ...",
        "CONNECTING TO DATABASE...": "ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ...",
        "LOADING COLLECTION...": "ЗАГРУЗКА КОЛЛЕКЦИИ...",
        "EMPTY COLLECTION": "ПУСТАЯ КОЛЛЕКЦИЯ",
        "ERROR LOADING DATA": "ОШИБКА ЗАГРУЗКИ ДАННЫХ",
        "CALCULATING 3D PROJECTION (PCA)...": "ВЫЧИСЛЕНИЕ 3D ПРОЕКЦИИ (PCA)...",
        "COMPLETED": "УСПЕШНО",
        "PCA FAILURE": "ОШИБКА PCA",
        "INITIALIZING GRAPHICS SCENE...": "ИНИЦИАЛИЗАЦИЯ 3D СЦЕНЫ...",
        "READY": "ГОТОВО",
        "LOADING OFFLINE DATA...": "ЗАГРУЗКА ЛОКАЛЬНЫХ ДАННЫХ...",
        "STANDALONE LOAD ERROR": "ОШИБКА ЛОКАЛЬНЫХ ДАННЫХ",
        "IDLE": "ОЖИДАНИЕ",
        "NO COLLECTIONS FOUND": "КОЛЛЕКЦИИ НЕ НАЙДЕНЫ",
        "CONNECTION ERROR": "ОШИБКА ПОДКЛЮЧЕНИЯ"
    },
    en: {
        "CONNECTING...": "CONNECTING...",
        "CONNECTING TO DATABASE...": "CONNECTING TO DATABASE...",
        "LOADING COLLECTION...": "LOADING COLLECTION...",
        "EMPTY COLLECTION": "EMPTY COLLECTION",
        "ERROR LOADING DATA": "ERROR LOADING DATA",
        "CALCULATING 3D PROJECTION (PCA)...": "CALCULATING 3D PROJECTION (PCA)...",
        "COMPLETED": "COMPLETED",
        "PCA FAILURE": "PCA FAILURE",
        "INITIALIZING GRAPHICS SCENE...": "INITIALIZING GRAPHICS SCENE...",
        "READY": "READY",
        "LOADING OFFLINE DATA...": "LOADING OFFLINE DATA...",
        "STANDALONE LOAD ERROR": "STANDALONE LOAD ERROR",
        "IDLE": "IDLE",
        "NO COLLECTIONS FOUND": "NO COLLECTIONS FOUND",
        "CONNECTION ERROR": "CONNECTION ERROR"
    }
};

function switchLanguage(lang) {
    state.language = lang;
    localStorage.setItem('qdrant_viz_lang', lang);
    
    // 1. Update document lang tag
    document.documentElement.lang = lang;
    
    // 2. Update text nodes with data-i18n attribute
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (TRANSLATIONS[lang]?.[key]) {
            el.innerHTML = TRANSLATIONS[lang][key];
        }
    });
    
    // 3. Update placeholder attributes
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        if (TRANSLATIONS[lang]?.[key]) {
            el.setAttribute('placeholder', TRANSLATIONS[lang][key]);
        }
    });
    
    // 4. Update active highlight in header toggle button
    const btnRu = document.getElementById('lang-ru');
    const btnEn = document.getElementById('lang-en');
    if (btnRu && btnEn) {
        if (lang === 'ru') {
            btnRu.style.color = '#fff';
            btnRu.style.textShadow = '0 0 5px var(--neon-cyan)';
            btnRu.style.fontWeight = 'bold';
            
            btnEn.style.color = 'rgba(255,255,255,0.4)';
            btnEn.style.textShadow = 'none';
            btnEn.style.fontWeight = 'normal';
        } else {
            btnEn.style.color = '#fff';
            btnEn.style.textShadow = '0 0 5px var(--neon-cyan)';
            btnEn.style.fontWeight = 'bold';
            
            btnRu.style.color = 'rgba(255,255,255,0.4)';
            btnRu.style.textShadow = 'none';
            btnRu.style.fontWeight = 'normal';
        }
    }
    
    // 5. Update dynamic UI values
    if (elements.pcaStatus) {
        const currentPca = elements.pcaStatus.textContent.trim();
        if (currentPca === 'COMPLETED' || currentPca === 'УСПЕШНО') {
            elements.pcaStatus.textContent = lang === 'ru' ? 'УСПЕШНО' : 'COMPLETED';
        } else if (currentPca === 'IDLE' || currentPca === 'ОЖИДАНИЕ') {
            elements.pcaStatus.textContent = lang === 'ru' ? 'ОЖИДАНИЕ' : 'IDLE';
        } else if (currentPca === 'FAILURE' || currentPca === 'ОШИБКА PCA') {
            elements.pcaStatus.textContent = lang === 'ru' ? 'ОШИБКА PCA' : 'FAILURE';
        }
    }
    
    if (elements.collectionSelect && elements.collectionSelect.children.length > 0) {
        for (let i = 0; i < elements.collectionSelect.children.length; i++) {
            const opt = elements.collectionSelect.children[i];
            if (opt.value === "") {
                opt.textContent = TRANSLATIONS[lang]["waiting-connection"];
            } else if (opt.textContent.startsWith("[Offline]") || opt.textContent.startsWith("[Локально]")) {
                opt.textContent = lang === 'ru' ? `[Локально] ${opt.value}` : `[Offline] ${opt.value}`;
            }
        }
    }
    
    // Update inspection default text if no node is selected
    if (selectedInstanceId === null && elements.metaText) {
        elements.metaText.textContent = TRANSLATIONS[lang]["inspect-default-text"];
    } else if (selectedInstanceId !== null) {
        // Refresh details for active node selection
        selectNode(selectedInstanceId);
    }
    
    // Update dynamic file filters list if empty
    if (elements.fileFilterList && elements.fileFilterList.children.length === 1 && elements.fileFilterList.children[0].style.textAlign === 'center') {
        elements.fileFilterList.children[0].textContent = TRANSLATIONS[lang]["no-file-metadata"];
    }
}

// Console logger helper for visual Loader Screen
function logToConsole(text, type = 'normal') {
    const time = new Date().toLocaleTimeString();
    const line = document.createElement('div');
    line.className = 'console-line';
    
    let colorClass = '';
    if (type === 'highlight') colorClass = 'highlight';
    if (type === 'error') colorClass = 'error';
    
    line.innerHTML = `
        <span class="console-time">[${time}]</span>
        <span class="console-text ${colorClass}">${text}</span>
    `;
    elements.loaderConsole.appendChild(line);
    elements.loaderConsole.scrollTop = elements.loaderConsole.scrollHeight;
    console.log(`[Visualizer Console] ${text}`);
}

function updateStatus(statusText) {
    const lang = state.language || 'ru';
    
    // Check for dynamic "LOADING COLLECTION"
    if (statusText.startsWith("LOADING COLLECTION \"")) {
        const colName = statusText.match(/"([^"]+)"/)?.[1] || "";
        if (lang === 'ru') {
            elements.loaderStatus.textContent = `ЗАГРУЗКА КОЛЛЕКЦИИ "${colName}"...`;
            return;
        } else {
            elements.loaderStatus.textContent = `LOADING COLLECTION "${colName}"...`;
            return;
        }
    }
    
    const translated = STATUS_TRANSLATIONS[lang]?.[statusText] || statusText;
    elements.loaderStatus.textContent = translated;
}

// ----------------------------------------------------
// 1. DATABASE CONNECTION & DATA FETCHING
// ----------------------------------------------------

async function loadLesQdrantData() {
    state.qdrantUrl = LES_QDRANT_URL;
    elements.loader.classList.remove('hidden');
    elements.loaderConsole.innerHTML = '';
    
    updateStatus("CONNECTING TO DATABASE...");
    logToConsole(`Reading LES Qdrant at ${state.qdrantUrl}...`);
    
    try {
        const response = await fetch(`${state.qdrantUrl}/collections`, { method: 'GET' });
        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
        
        const data = await response.json();
        state.collections = data.result.collections.map(c => c.name);
        
        if (state.collections.length === 0) {
            updateStatus("NO COLLECTIONS FOUND");
            elements.loader.classList.add('hidden');
            return;
        }
        
        const collectionToLoad = LES_COLLECTION_PRIORITY.find(c => state.collections.includes(c)) || state.collections[0];
        logToConsole(`Selected LES collection "${collectionToLoad}".`, 'highlight');
        await loadCollection(collectionToLoad);
        
    } catch (err) {
        logToConsole(`Connection failed: ${err.message}`, 'error');
        logToConsole(`Is local LES Qdrant running on ${state.qdrantUrl}?`, 'error');
        updateStatus("CONNECTION ERROR");
        const errMsg = `${TRANSLATIONS[state.language || 'ru']["toast-connect-fail"]} ${state.qdrantUrl}`;
        showToast(errMsg);
        elements.loader.classList.add('hidden');
    }
}

async function loadCollection(name) {
    if (!name) return;
    state.currentCollection = name;
    
    elements.loader.classList.remove('hidden');
    updateStatus(`LOADING COLLECTION "${name}"...`);
    logToConsole(`Fetching points from collection "${name}"...`);
    
    try {
        // Fetch up to 1500 points with both vectors and payloads
        const response = await fetch(`${state.qdrantUrl}/collections/${name}/points/scroll`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                limit: 1500,
                with_vector: true,
                with_payload: true
            })
        });
        
        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
        
        const data = await response.json();
        const points = data.result.points;
        
        if (!points || points.length === 0) {
            logToConsole(`Collection is empty.`, 'error');
            updateStatus("EMPTY COLLECTION");
            elements.loader.classList.add('hidden');
            return;
        }
        
        await applyPoints(points, name, 'Qdrant');
        
    } catch (err) {
        logToConsole(`Error loading collection: ${err.message}`, 'error');
        updateStatus("ERROR LOADING DATA");
    }
}

async function loadSnapshotData() {
    elements.loader.classList.remove('hidden');
    elements.loaderConsole.innerHTML = '';
    updateStatus("LOADING OFFLINE DATA...");
    logToConsole("Loading static snapshot from data.js...");

    try {
        const module = await import(`./data.js?v=${Date.now()}`);
        const backup = module.qdrantBackupData;
        if (!backup?.points?.length) throw new Error('data.js does not export qdrantBackupData.points');
        await applyPoints(backup.points, backup.collectionName || 'snapshot', 'data.js');
    } catch (err) {
        logToConsole(`Snapshot load failed: ${err.message}`, 'error');
        updateStatus("STANDALONE LOAD ERROR");
        showToast('Не удалось загрузить data.js рядом с визуализатором');
        elements.loader.classList.add('hidden');
    }
}

async function applyPoints(points, collectionName, sourceLabel) {
    state.currentCollection = collectionName;
    state.points = points;
    logToConsole(`Loaded ${points.length} points from ${sourceLabel}.`, 'highlight');

    const vectorDim = points[0].vector.length;
    elements.totalPoints.textContent = points.length;
    elements.vectorDim.textContent = vectorDim;

    prepareSnapshotDownload(collectionName, points);
    await runPCA();
    populateFileFilters();
    build3DScene();
}

function prepareSnapshotDownload(collectionName, points) {
    if (!elements.snapshotDownload) return;
    if (state.snapshotUrl) URL.revokeObjectURL(state.snapshotUrl);

    const exportStructure = {
        collectionName,
        exportDate: new Date().toISOString(),
        points,
    };
    const js = [
        '// Standalone backup data for LES Qdrant 3D Visualizer',
        `// Generated on: ${new Date().toLocaleString('sv-SE')}`,
        'export const qdrantBackupData = ',
        JSON.stringify(exportStructure, null, 2),
        ';',
        '',
    ].join('\n');

    const blob = new Blob([js], { type: 'text/javascript;charset=utf-8' });
    state.snapshotUrl = URL.createObjectURL(blob);
    elements.snapshotDownload.href = state.snapshotUrl;
    elements.snapshotDownload.classList.remove('disabled-link');
}

// ----------------------------------------------------
// 2. PRINCIPAL COMPONENT ANALYSIS (PCA) PROJECTOR
// ----------------------------------------------------

async function runPCA() {
    updateStatus("CALCULATING 3D PROJECTION (PCA)...");
    logToConsole(`Extracting ${state.points.length} vectors of dimension ${state.points[0].vector.length}...`);
    
    // We run the PCA on a slight delay to allow the loading UI to draw
    await new Promise(resolve => setTimeout(resolve, 100));
    
    try {
        const vectors = state.points.map(p => p.vector);
        
        logToConsole("Centering vectors and computing covariance matrix...");
        const pcaResult = PCA.project(vectors, 3);
        
        // Normalize projected coordinates so they lie comfortably in standard 3D space (-40 to 40)
        logToConsole("Projecting vectors onto top 3 Eigenvectors...");
        const pts = pcaResult.points;
        
        // Find boundaries
        let minX = Infinity, maxX = -Infinity;
        let minY = Infinity, maxY = -Infinity;
        let minZ = Infinity, maxZ = -Infinity;
        
        pts.forEach(p => {
            if (p[0] < minX) minX = p[0]; if (p[0] > maxX) maxX = p[0];
            if (p[1] < minY) minY = p[1]; if (p[1] > maxY) maxY = p[1];
            if (p[2] < minZ) minZ = p[2]; if (p[2] > maxZ) maxZ = p[2];
        });
        
        const sizeX = maxX - minX || 1;
        const sizeY = maxY - minY || 1;
        const sizeZ = maxZ - minZ || 1;
        
        const maxRange = Math.max(sizeX, sizeY, sizeZ);
        const scale = 80 / maxRange; // fit within [-40, 40]
        
        // Translate and scale to center of scene
        const centerX = minX + sizeX / 2;
        const centerY = minY + sizeY / 2;
        const centerZ = minZ + sizeZ / 2;
        
        state.baseProjectedPoints = pts.map(p => [
            (p[0] - centerX) * scale,
            (p[1] - centerY) * scale,
            (p[2] - centerZ) * scale
        ]);
        state.projectedPoints = spreadProjectedPoints(state.baseProjectedPoints, state.spreadStrength);
        
        logToConsole(`PCA completed successfully! Top eigenvalues: ${pcaResult.eigenvalues.map(v => v.toFixed(4)).join(", ")}`, 'highlight');
        elements.pcaStatus.textContent = state.language === 'ru' ? 'УСПЕШНО' : 'COMPLETED';
        
    } catch (err) {
        logToConsole(`PCA Calculation failed: ${err.message}`, 'error');
        updateStatus("PCA FAILURE");
        throw err;
    }
}

function stableNoise(index, salt) {
    const x = Math.sin(index * 127.1 + salt * 311.7) * 43758.5453;
    return x - Math.floor(x);
}

function stableUnitVector(key) {
    let hash = 0;
    for (let i = 0; i < key.length; i++) {
        hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0;
    }
    const a = stableNoise(Math.abs(hash), 7) * Math.PI * 2;
    const z = stableNoise(Math.abs(hash), 11) * 2 - 1;
    const r = Math.sqrt(Math.max(0, 1 - z * z));
    return new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, z);
}

function documentCounts() {
    const counts = new Map();
    state.points.forEach(point => {
        const fileName = point.payload?.file_name || '';
        counts.set(fileName, (counts.get(fileName) || 0) + 1);
    });
    return counts;
}

function spreadProjectedPoints(points, strength) {
    if (!points.length || strength <= 0) return points.map(p => [...p]);

    const spread = Math.min(Math.max(strength, 0), 3.0);
    const docSpread = Math.min(Math.max(state.documentSpread, 0), 3.0);
    const counts = documentCounts();
    const result = points.map((p, i) => {
        const fileName = state.points[i]?.payload?.file_name || '';
        const fileCount = counts.get(fileName) || 1;
        const fileFan = stableUnitVector(fileName).multiplyScalar(docSpread * (7.0 + Math.log2(fileCount + 1) * 1.6));
        const jitter = 1.2 * spread;
        return new THREE.Vector3(
            p[0] + fileFan.x + (stableNoise(i, 1) - 0.5) * jitter,
            p[1] + fileFan.y + (stableNoise(i, 2) - 0.5) * jitter,
            p[2] + fileFan.z + (stableNoise(i, 3) - 0.5) * jitter
        );
    });

    const minDist = 2.6 + spread * 3.2;
    const minDistSq = minDist * minDist;
    const stiffness = 0.18 * spread;
    const iterations = Math.round(8 + spread * 8);
    const neighborOffsets = [];
    for (let x = -1; x <= 1; x++) {
        for (let y = -1; y <= 1; y++) {
            for (let z = -1; z <= 1; z++) {
                neighborOffsets.push([x, y, z]);
            }
        }
    }

    for (let iter = 0; iter < iterations; iter++) {
        const cells = new Map();
        for (let i = 0; i < result.length; i++) {
            const p = result[i];
            const key = `${Math.floor(p.x / minDist)},${Math.floor(p.y / minDist)},${Math.floor(p.z / minDist)}`;
            if (!cells.has(key)) cells.set(key, []);
            cells.get(key).push(i);
        }

        for (let i = 0; i < result.length; i++) {
            const a = result[i];
            const cx = Math.floor(a.x / minDist);
            const cy = Math.floor(a.y / minDist);
            const cz = Math.floor(a.z / minDist);

            for (const [ox, oy, oz] of neighborOffsets) {
                const bucket = cells.get(`${cx + ox},${cy + oy},${cz + oz}`);
                if (!bucket) continue;
                for (const j of bucket) {
                    if (j <= i) continue;
                    const b = result[j];
                    const dx = b.x - a.x;
                    const dy = b.y - a.y;
                    const dz = b.z - a.z;
                    const distSq = dx * dx + dy * dy + dz * dz;
                    if (distSq <= 0.0001 || distSq >= minDistSq) continue;

                    const dist = Math.sqrt(distSq);
                    const push = Math.min((minDist - dist) * stiffness, minDist * 0.45);
                    const ux = dx / dist;
                    const uy = dy / dist;
                    const uz = dz / dist;
                    a.x -= ux * push;
                    a.y -= uy * push;
                    a.z -= uz * push;
                    b.x += ux * push;
                    b.y += uy * push;
                    b.z += uz * push;
                }
            }
        }

        const centerPull = 0.009 * spread;
        for (let i = 0; i < result.length; i++) {
            const base = points[i];
            result[i].x += (base[0] - result[i].x) * centerPull;
            result[i].y += (base[1] - result[i].y) * centerPull;
            result[i].z += (base[2] - result[i].z) * centerPull;
        }
    }

    return result.map(v => [v.x, v.y, v.z]);
}

function applySpreadLayout() {
    if (!state.baseProjectedPoints.length) return;

    state.projectedPoints = spreadProjectedPoints(state.baseProjectedPoints, state.spreadStrength);
    targetInstancePositions = state.projectedPoints.map(([x, y, z]) => new THREE.Vector3(x, y, z));

    if (transitionProgress >= 1.0) {
        updateNodeVisuals();
    }
    buildConstellationLines();
    focusSelectedFiles();
}

function colorForFile(fileName) {
    const key = fileName || '';
    let hash = 0;
    for (let i = 0; i < key.length; i++) {
        hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0;
    }
    const color = FILE_HIGHLIGHT_COLORS[Math.abs(hash) % FILE_HIGHLIGHT_COLORS.length];
    return new THREE.Color(color);
}

// Fill UI sidebar file checklist based on unique files in payload
function populateFileFilters() {
    elements.fileFilterList.innerHTML = '';
    state.selectedFiles.clear();
    
    // Extract unique file names
    const files = new Set();
    state.points.forEach(p => {
        if (p.payload && p.payload.file_name) {
            files.add(p.payload.file_name);
        }
    });
    
    if (files.size === 0) {
        elements.fileFilterList.innerHTML = `<div style="font-size:0.7rem;color:var(--text-dim);text-align:center;padding:10px;">${TRANSLATIONS[state.language || 'ru']["no-file-metadata"]}</div>`;
        return;
    }
    
    Array.from(files).sort().forEach(file => {
        const item = document.createElement('div');
        item.className = 'file-filter-item';
        item.dataset.filename = file;
        
        const checkbox = document.createElement('div');
        checkbox.className = 'file-filter-checkbox';

        const swatch = document.createElement('div');
        swatch.className = 'file-filter-swatch';
        swatch.style.backgroundColor = `#${colorForFile(file).getHexString()}`;
        
        const nameSpan = document.createElement('span');
        nameSpan.className = 'file-filter-name';
        nameSpan.textContent = file;
        nameSpan.title = file;
        
        item.appendChild(checkbox);
        item.appendChild(swatch);
        item.appendChild(nameSpan);
        
        item.addEventListener('click', () => {
            if (state.selectedFiles.has(file)) {
                state.selectedFiles.delete(file);
                checkbox.classList.remove('checked');
                item.classList.remove('selected');
            } else {
                state.selectedFiles.add(file);
                checkbox.classList.add('checked');
                item.classList.add('selected');
            }
            updateNodeVisuals();
            buildConstellationLines();
            focusSelectedFiles();
        });
        
        elements.fileFilterList.appendChild(item);
    });
}

// ----------------------------------------------------
// 3. THREE.JS 3D SCENE INITIALIZATION & GRAPHICS
// ----------------------------------------------------

function build3DScene() {
    updateStatus("INITIALIZING GRAPHICS SCENE...");
    logToConsole("Configuring Three.js context, canvas, lighting & controls...");
    
    // 1. Clean up existing scene if re-loading
    if (requestId) {
        cancelAnimationFrame(requestId);
        requestId = null;
    }
    
    const container = document.getElementById('canvas-container');
    container.innerHTML = ''; // Clear canvas
    
    // 2. Setup Camera, Scene and Renderer
    scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x060913, 0.007);
    
    camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(60, 40, 70);
    
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x060913, 1);
    container.appendChild(renderer.domElement);
    
    // 3. Orbit Controls
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.maxDistance = 300;
    controls.minDistance = 5;
    controls.autoRotate = state.autoRotate;
    controls.autoRotateSpeed = 0.5;
    
    // 4. Lights
    ambientLight = new THREE.AmbientLight(0x080f26, 1.5);
    scene.add(ambientLight);
    
    directionalLight = new THREE.DirectionalLight(0x00f0ff, 2.0);
    directionalLight.position.set(50, 100, 50);
    scene.add(directionalLight);
    
    pointLight = new THREE.PointLight(0xff007f, 3.0, 150);
    pointLight.position.set(-50, -20, -50);
    scene.add(pointLight);
    
    // 5. Star Dust background particles
    const starCount = 3000;
    const starGeo = new THREE.BufferGeometry();
    const starPositions = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount * 3; i += 3) {
        starPositions[i] = (Math.random() - 0.5) * 500;
        starPositions[i+1] = (Math.random() - 0.5) * 500;
        starPositions[i+2] = (Math.random() - 0.5) * 500;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    const starMat = new THREE.PointsMaterial({
        color: 0xffffff,
        size: 0.8,
        transparent: true,
        opacity: 0.3,
        sizeAttenuation: true
    });
    starField = new THREE.Points(starGeo, starMat);
    scene.add(starField);
    
    // 6. Glowing cyber grid (enhanced visibility for 3D depth)
    gridHelper = new THREE.GridHelper(160, 32, 0x00e5ff, 0x084060);
    gridHelper.position.y = -45;
    gridHelper.material.opacity = 0.35;
    gridHelper.material.transparent = true;
    scene.add(gridHelper);
    
    // 7. BUILD INSTANCED SPHERES (The Vector Nodes)
    logToConsole("Creating high-performance sphere instanced meshes...");
    const nodeCount = state.points.length;
    
    // Low polygon count per sphere ensures fast render speeds
    const sphereGeo = new THREE.SphereGeometry(state.nodeSize * 0.4, 8, 8);
    const sphereMat = new THREE.MeshBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.95,
        vertexColors: true
    });
    
    instancedMesh = new THREE.InstancedMesh(sphereGeo, sphereMat, nodeCount);
    
    // Initialize animation values
    initialInstancePositions = [];
    targetInstancePositions = [];
    
    const dummy = new THREE.Object3D();
    for (let i = 0; i < nodeCount; i++) {
        // PCA final coordinates
        const [tx, ty, tz] = state.projectedPoints[i];
        targetInstancePositions.push(new THREE.Vector3(tx, ty, tz));
        
        // Random starting coordinates on a large sphere outer shell
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos((Math.random() * 2) - 1);
        const radius = 150 + Math.random() * 50;
        const rx = radius * Math.sin(phi) * Math.cos(theta);
        const ry = radius * Math.sin(phi) * Math.sin(theta);
        const rz = radius * Math.cos(phi);
        
        initialInstancePositions.push(new THREE.Vector3(rx, ry, rz));
        
        dummy.position.set(rx, ry, rz);
        dummy.updateMatrix();
        instancedMesh.setMatrixAt(i, dummy.matrix);
        instancedMesh.setColorAt(i, COLOR_NORMAL);
    }
    
    instancedMesh.instanceMatrix.needsUpdate = true;
    if (instancedMesh.instanceColor) instancedMesh.instanceColor.needsUpdate = true;
    scene.add(instancedMesh);

    // 7.1 BUILD NEURAL GLOW HALOS (The shimmering point light overlay)
    const glowGeo = new THREE.BufferGeometry();
    const glowPositions = new Float32Array(nodeCount * 3);
    const glowColors = new Float32Array(nodeCount * 3);
    
    for (let i = 0; i < nodeCount; i++) {
        const pos = initialInstancePositions[i];
        glowPositions[i*3] = pos.x;
        glowPositions[i*3+1] = pos.y;
        glowPositions[i*3+2] = pos.z;
        
        glowColors[i*3] = COLOR_NORMAL.r;
        glowColors[i*3+1] = COLOR_NORMAL.g;
        glowColors[i*3+2] = COLOR_NORMAL.b;
    }
    
    glowGeo.setAttribute('position', new THREE.BufferAttribute(glowPositions, 3));
    glowGeo.setAttribute('color', new THREE.BufferAttribute(glowColors, 3));
    
    const glowMat = new THREE.PointsMaterial({
        size: state.nodeSize * 4.0 * state.glowIntensity,
        map: createGlowTexture(),
        transparent: true,
        opacity: 0.85 * state.glowIntensity,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        vertexColors: true
    });
    
    glowMesh = new THREE.Points(glowGeo, glowMat);
    scene.add(glowMesh);
    
    // 8. CONSTELLATION NEURAL NET LINES
    buildConstellationLines();
    
    // Trigger entrance transition animation
    transitionProgress = 0.0;
    
    // Hide Loader
    updateStatus("READY");
    logToConsole("Render pipeline active. 60 FPS visual rendering engaged.", "highlight");
    
    setTimeout(() => {
        elements.loader.classList.add('hidden');
    }, 600);
    
    // Setup listeners
    window.addEventListener('resize', onWindowResize);
    renderer.domElement.addEventListener('mousemove', onMouseMove);
    renderer.domElement.addEventListener('click', onMouseClick);
    
    // Start loop
    animate();
}

// Nearest-neighbor constellations
function buildConstellationLines() {
    if (constellationLines) {
        scene.remove(constellationLines);
        constellationLines.geometry.dispose();
        constellationLines.material.dispose();
        constellationLines = null;
    }
    
    if (!state.showConstellation) return;
    
    logToConsole("Computing constellation semantic nearest neighbor paths...");
    const positions = [];
    const colors = [];
    const n = state.points.length;
    const k = state.constellationNeighbors;
    
    // Compute connections in PCA 3D space (faster and visually cleaner)
    for (let i = 0; i < n; i++) {
        const p1 = targetInstancePositions[i];
        
        // Find closest points
        const dists = [];
        for (let j = 0; j < n; j++) {
            if (i === j) continue;
            const p2 = targetInstancePositions[j];
            const d = p1.distanceToSquared(p2);
            dists.push({ index: j, dist: d });
        }
        
        dists.sort((a, b) => a.dist - b.dist);
        
        // Take top k neighbors and add line segments
        for (let idx = 0; idx < Math.min(k, dists.length); idx++) {
            const neighborIdx = dists[idx].index;
            const p2 = targetInstancePositions[neighborIdx];
            const fileA = state.points[i]?.payload?.file_name || '';
            const fileB = state.points[neighborIdx]?.payload?.file_name || '';
            let lineColor = new THREE.Color('#00e5ff');
            let opacity = 0.35;

            if (state.selectedFiles.size > 0) {
                const aSelected = state.selectedFiles.has(fileA);
                const bSelected = state.selectedFiles.has(fileB);
                if (aSelected && bSelected && fileA === fileB) {
                    lineColor = colorForFile(fileA);
                    opacity = 0.75;
                } else if (aSelected || bSelected) {
                    lineColor = colorForFile(aSelected ? fileA : fileB);
                    opacity = 0.45;
                } else {
                    lineColor = new THREE.Color('#0d1a2f');
                    opacity = 0.12;
                }
            }
            
            positions.push(p1.x, p1.y, p1.z);
            positions.push(p2.x, p2.y, p2.z);
            
            colors.push(lineColor.r * opacity, lineColor.g * opacity, lineColor.b * opacity);
            colors.push(lineColor.r * opacity, lineColor.g * opacity, lineColor.b * opacity);
        }
    }
    
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    lineGeo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    
    // Standard LineBasicMaterial doesn't support alpha values per vertex well on some systems, 
    // but using vertexColors works extremely well.
    const lineMat = new THREE.LineBasicMaterial({
        transparent: true,
        opacity: 0.35 * state.glowIntensity,
        blending: THREE.AdditiveBlending,
        vertexColors: true
    });
    
    constellationLines = new THREE.LineSegments(lineGeo, lineMat);
    scene.add(constellationLines);
}

// ----------------------------------------------------
// 4. ANIMATION LOOP & TRANSITIONS
// ----------------------------------------------------

function animate() {
    requestId = requestAnimationFrame(animate);
    
    // 1. Damping controls update
    controls.update();
    
    // 2. Slow spin starry sky
    if (starField) {
        starField.rotation.y += 0.0003;
        starField.rotation.x += 0.0001;
    }
    
    // 3. Smooth morph entry animation (Lerping positions)
    if (transitionProgress < 1.0) {
        transitionProgress += transitionSpeed;
        if (transitionProgress > 1.0) transitionProgress = 1.0;
        
        const dummy = new THREE.Object3D();
        const nodeCount = state.points.length;
        
        for (let i = 0; i < nodeCount; i++) {
            const initial = initialInstancePositions[i];
            const target = targetInstancePositions[i];
            
            // Smooth step interpolation
            const t = easeInOutCubic(transitionProgress);
            const currentPos = new THREE.Vector3().lerpVectors(initial, target, t);
            
            dummy.position.copy(currentPos);
            
            // Visual pulse scale during entrance
            const scalePulse = transitionProgress < 1.0 ? 1.0 + Math.sin(t * Math.PI) * 0.4 : 1.0;
            dummy.scale.set(scalePulse, scalePulse, scalePulse);
            
            dummy.updateMatrix();
            instancedMesh.setMatrixAt(i, dummy.matrix);
            
            // Sync glowing halo positions in real-time
            if (glowMesh) {
                const glowPositions = glowMesh.geometry.attributes.position.array;
                glowPositions[i*3] = currentPos.x;
                glowPositions[i*3+1] = currentPos.y;
                glowPositions[i*3+2] = currentPos.z;
            }
        }
        instancedMesh.instanceMatrix.needsUpdate = true;
        
        if (glowMesh) {
            glowMesh.geometry.attributes.position.needsUpdate = true;
        }
        
        // Sync lines entry
        if (constellationLines) {
            constellationLines.scale.setScalar(transitionProgress);
        }
    }
    
    renderer.render(scene, camera);
}

// Easing helper
function easeInOutCubic(x) {
    return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

// ----------------------------------------------------
// 5. SELECTION, HOVER, SEARCH & FILTER
// ----------------------------------------------------

// Recalculates colors of nodes based on hover state, search matching, and file filters
function updateNodeVisuals() {
    if (!instancedMesh) return;
    
    const nodeCount = state.points.length;
    const query = state.searchQuery.toLowerCase();
    
    for (let i = 0; i < nodeCount; i++) {
        const point = state.points[i];
        const payload = point.payload || {};
        const textContent = (payload.text || '').toLowerCase();
        const fileName = (payload.file_name || '').toLowerCase();
        
        const isSelectedFile = state.selectedFiles.has(payload.file_name);
        const hasDocumentHighlight = state.selectedFiles.size > 0;
        let color = hasDocumentHighlight
            ? (isSelectedFile ? colorForFile(payload.file_name).lerp(COLOR_SELECT, 0.16) : COLOR_CONTEXT.clone())
            : COLOR_NORMAL.clone();
        let scale = 1.0;

        if (hasDocumentHighlight) {
            scale = isSelectedFile ? 2.8 : 0.38;
        }

        // Search query dims non-matches without losing selected document colors.
        if (query.length > 0) {
            const isMatch = textContent.includes(query) || fileName.includes(query);
            if (isMatch) {
                if (!hasDocumentHighlight) color = COLOR_MATCH.clone();
                scale = hasDocumentHighlight && isSelectedFile ? 3.0 : 1.3;
            } else {
                color = COLOR_DIM.clone();
                scale = 0.5;
            }
        }

        // Selection and hover remain strongest visual states.
        if (i === selectedInstanceId) {
            color = COLOR_SELECT.clone();
            scale = 1.65;
        } else if (i === hoveredInstanceId) {
            color = COLOR_HOVER.clone();
            scale = 1.45;
        }
        
        instancedMesh.setColorAt(i, color);
        
        // Sync glowing halo colors
        if (glowMesh) {
            const glowColors = glowMesh.geometry.attributes.color.array;
            glowColors[i*3] = color.r;
            glowColors[i*3+1] = color.g;
            glowColors[i*3+2] = color.b;
        }
        
        // Update scales of instances (requires updating matrices)
        if (transitionProgress >= 1.0) {
            const dummy = new THREE.Object3D();
            dummy.position.copy(targetInstancePositions[i]);
            dummy.scale.set(scale, scale, scale);
            dummy.updateMatrix();
            instancedMesh.setMatrixAt(i, dummy.matrix);
            
            // Sync static position for glow mesh if selection scaled
            if (glowMesh) {
                const glowPositions = glowMesh.geometry.attributes.position.array;
                glowPositions[i*3] = targetInstancePositions[i].x;
                glowPositions[i*3+1] = targetInstancePositions[i].y;
                glowPositions[i*3+2] = targetInstancePositions[i].z;
            }
        }
    }
    
    if (instancedMesh.instanceColor) instancedMesh.instanceColor.needsUpdate = true;
    instancedMesh.instanceMatrix.needsUpdate = true;
    
    if (glowMesh) {
        glowMesh.geometry.attributes.color.needsUpdate = true;
        glowMesh.geometry.attributes.position.needsUpdate = true;
    }

    updateSelectedDocumentOverlay();
}

function updateSelectedDocumentOverlay() {
    if (!scene) return;
    if (selectedDocumentMesh) {
        scene.remove(selectedDocumentMesh);
        selectedDocumentMesh.traverse(child => {
            if (child.geometry) child.geometry.dispose();
            if (child.material) child.material.dispose();
        });
        selectedDocumentMesh = null;
    }
    if (state.selectedFiles.size === 0 || transitionProgress < 1.0) return;

    const byFile = new Map();
    for (let i = 0; i < state.points.length; i++) {
        const fileName = state.points[i]?.payload?.file_name || '';
        if (!state.selectedFiles.has(fileName)) continue;

        const pos = targetInstancePositions[i];
        if (!byFile.has(fileName)) byFile.set(fileName, []);
        byFile.get(fileName).push(pos);
    }
    if (byFile.size === 0) return;

    const geo = new THREE.SphereGeometry(Math.max(0.9, state.nodeSize * 1.45), 12, 12);
    selectedDocumentMesh = new THREE.Group();
    selectedDocumentMesh.renderOrder = 20;
    const dummy = new THREE.Object3D();

    byFile.forEach((positions, fileName) => {
        const mat = new THREE.MeshBasicMaterial({
            color: colorForFile(fileName).lerp(COLOR_SELECT, 0.12),
            transparent: true,
            opacity: 1,
            depthTest: false,
            depthWrite: false,
        });
        const mesh = new THREE.InstancedMesh(geo.clone(), mat, positions.length);
        mesh.renderOrder = 20;
        positions.forEach((pos, i) => {
            dummy.position.copy(pos);
            dummy.updateMatrix();
            mesh.setMatrixAt(i, dummy.matrix);
        });
        mesh.instanceMatrix.needsUpdate = true;
        selectedDocumentMesh.add(mesh);
    });

    scene.add(selectedDocumentMesh);
}

function focusSelectedFiles() {
    if (!camera || !controls || state.selectedFiles.size === 0 || !targetInstancePositions.length) return;

    const selectedPositions = [];
    for (let i = 0; i < state.points.length; i++) {
        const fileName = state.points[i]?.payload?.file_name || '';
        if (state.selectedFiles.has(fileName)) {
            selectedPositions.push(targetInstancePositions[i]);
        }
    }
    if (!selectedPositions.length) return;

    const center = new THREE.Vector3();
    selectedPositions.forEach(pos => center.add(pos));
    center.divideScalar(selectedPositions.length);

    let radius = 8;
    selectedPositions.forEach(pos => {
        radius = Math.max(radius, center.distanceTo(pos));
    });

    const direction = new THREE.Vector3().subVectors(camera.position, controls.target);
    if (direction.lengthSq() < 0.001) direction.set(1, 0.7, 1);
    direction.normalize();

    const distance = Math.min(Math.max(radius * 2.8, 32), 140);
    controls.target.copy(center);
    camera.position.copy(center).add(direction.multiplyScalar(distance));
    camera.lookAt(center);
    controls.update();
}

function onMouseMove(event) {
    mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
    
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObject(instancedMesh);
    
    if (intersects.length > 0) {
        const instanceId = intersects[0].instanceId;
        if (hoveredInstanceId !== instanceId) {
            hoveredInstanceId = instanceId;
            document.body.style.cursor = 'pointer';
            updateNodeVisuals();
        }
    } else {
        if (hoveredInstanceId !== null) {
            hoveredInstanceId = null;
            document.body.style.cursor = 'default';
            updateNodeVisuals();
        }
    }
}

function onMouseClick(event) {
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObject(instancedMesh);
    
    if (intersects.length > 0) {
        const instanceId = intersects[0].instanceId;
        selectNode(instanceId);
    }
}

function selectNode(instanceId) {
    selectedInstanceId = instanceId;
    state.selectedPointId = state.points[instanceId].id;
    updateNodeVisuals();
    
    // Load metadata details
    const p = state.points[instanceId];
    const payload = p.payload || {};
    const coords = targetInstancePositions[instanceId];
    
    const activeLang = state.language || 'ru';
    elements.metaId.textContent = p.id;
    elements.metaFile.textContent = payload.file_name || TRANSLATIONS[activeLang]["no-file-name"];
    elements.metaDocId.textContent = payload.doc_id || 'N/A';
    elements.metaCoords.textContent = `X: ${coords.x.toFixed(2)}, Y: ${coords.y.toFixed(2)}, Z: ${coords.z.toFixed(2)}`;
    
    // Render text snippet beautifully
    let text = payload.text || '';
    // If it looks like base64 / encrypted and long, we add a toggle to reveal or format it
    if (text.length > 300 && /^[a-zA-Z0-9+/=]+$/.test(text.substring(0, 100).replace(/\s/g, ""))) {
        const encryptLabel = TRANSLATIONS[activeLang]["inspect-encrypted-text"];
        elements.metaText.innerHTML = `
            <div style="color:var(--neon-magenta);font-weight:700;margin-bottom:6px;font-size:0.7rem;">${encryptLabel}</div>
            <div style="word-break:break-all;font-family:var(--font-mono);opacity:0.6;">${text}</div>
        `;
    } else {
        elements.metaText.textContent = text || TRANSLATIONS[activeLang]["inspect-empty-text"];
    }
    
    elements.detailPanel.classList.add('visible');
}

function closeDetail() {
    selectedInstanceId = null;
    state.selectedPointId = null;
    elements.detailPanel.classList.remove('visible');
    updateNodeVisuals();
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

// Toast warning / helper alert
function showToast(message) {
    // Remove existing
    const existing = document.querySelector('.toast-msg');
    if (existing) existing.remove();
    
    const toast = document.createElement('div');
    toast.className = 'toast-msg';
    toast.textContent = message;
    document.body.appendChild(toast);
}

// ----------------------------------------------------
// 6. GUI / CONTROL PANEL ATTACHMENTS
// ----------------------------------------------------

function setupGUIEvents() {
    elements.loadLesBtn.addEventListener('click', loadLesQdrantData);
    elements.loadSnapshotBtn.addEventListener('click', loadSnapshotData);
    
    // Node Size slider
    elements.nodeSizeSlider.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        state.nodeSize = val;
        elements.nodeSizeVal.textContent = val.toFixed(1);
        
        if (instancedMesh) {
            // Re-create geometry or just rescale matrices
            scene.remove(instancedMesh);
            
            const sphereGeo = new THREE.SphereGeometry(state.nodeSize * 0.4, 8, 8);
            const sphereMat = new THREE.MeshBasicMaterial({
                color: 0xffffff,
                transparent: true,
                opacity: 0.95,
                vertexColors: true
            });
            
            const newMesh = new THREE.InstancedMesh(sphereGeo, sphereMat, state.points.length);
            for (let i = 0; i < state.points.length; i++) {
                const matrix = new THREE.Matrix4();
                instancedMesh.getMatrixAt(i, matrix);
                newMesh.setMatrixAt(i, matrix);
                
                const color = new THREE.Color();
                instancedMesh.getColorAt(i, color);
                newMesh.setColorAt(i, color);
            }
            instancedMesh = newMesh;
            instancedMesh.instanceMatrix.needsUpdate = true;
            if (instancedMesh.instanceColor) instancedMesh.instanceColor.needsUpdate = true;
            scene.add(instancedMesh);
            
            // Rescale glow halos dynamically
            if (glowMesh) {
                glowMesh.material.size = state.nodeSize * 4.0 * state.glowIntensity;
            }
            
            updateNodeVisuals();
        }
    });
    
    // Glow slider - Adjusts intensity of lighting in scene
    elements.glowSlider.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        state.glowIntensity = val;
        elements.glowVal.textContent = val.toFixed(1);
        
        if (directionalLight) directionalLight.intensity = 2.0 * val;
        if (pointLight) pointLight.intensity = 3.0 * val;
        
        // Dynamically swell glow halos and constellation lines
        if (glowMesh) {
            glowMesh.material.size = state.nodeSize * 4.0 * val;
            glowMesh.material.opacity = 0.85 * val;
        }
        if (constellationLines) {
            constellationLines.material.opacity = 0.35 * val;
        }
    });
    
    // Neighbors constellation slider
    elements.neighborsSlider.addEventListener('input', (e) => {
        const val = parseInt(e.target.value);
        state.constellationNeighbors = val;
        elements.neighborsVal.textContent = val;
        buildConstellationLines();
    });

    elements.spreadSlider.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        state.spreadStrength = val;
        elements.spreadVal.textContent = val.toFixed(1);
        applySpreadLayout();
    });

    elements.docSpreadSlider.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        state.documentSpread = val;
        elements.docSpreadVal.textContent = val.toFixed(1);
        applySpreadLayout();
    });
    
    // Toggles
    elements.toggleGrid.addEventListener('change', (e) => {
        state.showGrid = e.target.checked;
        if (gridHelper) gridHelper.visible = state.showGrid;
    });
    
    elements.toggleConstellation.addEventListener('change', (e) => {
        state.showConstellation = e.target.checked;
        buildConstellationLines();
    });
    
    elements.toggleRotate.addEventListener('change', (e) => {
        state.autoRotate = e.target.checked;
        if (controls) controls.autoRotate = state.autoRotate;
    });
    
    // Search
    elements.searchInput.addEventListener('input', (e) => {
        state.searchQuery = e.target.value.trim();
        updateNodeVisuals();
    });
    
    // Close sidebar
    elements.closeDetailBtn.addEventListener('click', closeDetail);

    if (elements.helpToggleBtn && elements.instructionsBar) {
        const setHelpVisible = (visible) => {
            elements.instructionsBar.classList.toggle('is-collapsed', !visible);
            elements.helpToggleBtn.classList.toggle('panel-open', visible);
            elements.helpToggleBtn.textContent = visible ? 'Скрыть управление' : 'Управление';
            elements.helpToggleBtn.setAttribute('aria-expanded', String(visible));
            localStorage.setItem('qdrant_viz_help_visible', String(visible));
        };
        setHelpVisible(localStorage.getItem('qdrant_viz_help_visible') === 'true');
        elements.helpToggleBtn.addEventListener('click', () => {
            const visible = elements.instructionsBar.classList.contains('is-collapsed');
            setHelpVisible(visible);
        });
    }
}

// ----------------------------------------------------
// 7. INITIALIZE WEB APPLICATION ON PAGE LOAD
// ----------------------------------------------------

window.addEventListener('DOMContentLoaded', () => {
    setupGUIEvents();

    // Initialize localization from localStorage or default 'ru'
    const savedLang = localStorage.getItem('qdrant_viz_lang') || 'ru';
    switchLanguage(savedLang);
});

// Dynamic glowing neural halo particle generator
function createGlowTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    
    // Create soft neon radial gradient
    const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, 'rgba(255, 255, 255, 1.0)');
    gradient.addColorStop(0.15, 'rgba(0, 240, 255, 0.85)');
    gradient.addColorStop(0.4, 'rgba(0, 40, 150, 0.45)');
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
    
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 64, 64);
    
    return new THREE.CanvasTexture(canvas);
}
