const tasks = [
  {
    id: "FAM-0241",
    title: "Шкаф архивный металлический",
    category: "Мебель",
    owner: "Илья Морозов",
    due: "12 июн",
    fop: "ADSK_Company_2026",
    status: "ready",
    statusText: "Готово к разработке",
    score: "86%",
    aiSummary:
      "ТЗ и таблица типоразмеров согласованы. ФОП покрывает 12 из 14 обязательных параметров. Для материала фасада нужен выбор из корпоративного справочника.",
    sources: [
      ["ТЗ_шкаф_архивный.pdf", "PDF · 8 стр · загружено сегодня"],
      ["Типоразмеры_шкафы.xlsx", "XLSX · 6 типов · 18 параметров"],
      ["ADSK_Company_2026.txt", "ФОП · 418 параметров"],
      ["Furniture_Metric.rft", "Шаблон · категория Furniture"],
    ],
    parameters: [
      ["ADSK_Наименование", "Text", "Shared"],
      ["ADSK_Код изделия", "Text", "Shared"],
      ["Ширина", "Length", "Family"],
      ["Высота", "Length", "Family"],
      ["Глубина", "Length", "Family"],
      ["Материал корпуса", "Material", "Family"],
    ],
    types: [
      ["Шкаф 800x400x1800", "800", "400", "1800", "серый RAL 7035"],
      ["Шкаф 900x450x1800", "900", "450", "1800", "серый RAL 7035"],
      ["Шкаф 1000x500x2000", "1000", "500", "2000", "графит RAL 7024"],
    ],
    checks: [
      ["pass", "Категория семейства", "Furniture совпадает со спецификацией"],
      ["pass", "Обязательные параметры", "12 параметров найдены в ФОП"],
      ["warn", "Материалы", "2 материала требуют выбора из справочника"],
      ["warn", "Типоразмеры", "Нужно подтвердить 6 строк перед созданием"],
    ],
    risks: [
      ["M", "medium", "Материал фасада", "В ТЗ указано два допустимых покрытия без правила выбора."],
      ["L", "low", "Артикул", "Формула артикула зависит от финального кода серии."],
    ],
    actions: [
      ["file-plus-2", "Создать параметры", "Добавить 12 shared и 2 family parameters"],
      ["table-2", "Создать типы", "Сформировать 6 типоразмеров из Excel"],
      ["clipboard-check", "Запустить проверку", "Сверить активный RFA со спецификацией"],
    ],
  },
  {
    id: "FAM-0242",
    title: "Дверь техническая EI60",
    category: "Двери",
    owner: "Анна Лебедева",
    due: "15 июн",
    fop: "DoorPack_2026",
    status: "review",
    statusText: "На проверке",
    score: "72%",
    aiSummary:
      "Геометрия и типы загружены. Проверка нашла незаполненные классификаторы и конфликт единиц у параметра толщины полотна.",
    sources: [
      ["ТЗ_дверь_EI60.docx", "DOCX · 12 стр"],
      ["EI60_types.xlsx", "XLSX · 14 типов"],
      ["DoorPack_2026.txt", "ФОП · 216 параметров"],
    ],
    parameters: [
      ["ADSK_Наименование", "Text", "Shared"],
      ["ADSK_Класс огнестойкости", "Text", "Shared"],
      ["Ширина проема", "Length", "Family"],
      ["Высота проема", "Length", "Family"],
      ["Толщина полотна", "Length", "Family"],
    ],
    types: [
      ["EI60 900x2100 L", "900", "140", "2100", "RAL 7035"],
      ["EI60 1000x2100 R", "1000", "140", "2100", "RAL 7035"],
      ["EI60 1200x2200 L", "1200", "160", "2200", "RAL 7016"],
    ],
    checks: [
      ["pass", "Типы", "14 типов найдены"],
      ["fail", "Классификатор", "ADSK_Код изделия пуст у 4 типов"],
      ["warn", "Единицы", "Толщина полотна прочитана как Text"],
      ["pass", "Файл", "Размер RFA в пределах нормы"],
    ],
    risks: [
      ["H", "high", "Классификатор", "Без кода изделие нельзя публиковать в каталог."],
      ["M", "medium", "Единицы", "Нужно привести толщину полотна к Length."],
    ],
    actions: [
      ["list-checks", "Исправить значения", "Заполнить 4 пустых кода изделия"],
      ["ruler", "Проверить единицы", "Сопоставить толщину полотна с ФОП"],
      ["send", "Вернуть на доработку", "Сформировать замечания разработчику"],
    ],
  },
  {
    id: "FAM-0238",
    title: "Светильник линейный подвесной",
    category: "Осветительные приборы",
    owner: "Сергей Ким",
    due: "18 июн",
    fop: "MEP_Light_2026",
    status: "dev",
    statusText: "В работе",
    score: "64%",
    aiSummary:
      "Спецификация готова частично. Таблица мощностей распознана, но для фотометрии нет исходного IES-файла.",
    sources: [
      ["brief_linear_light.pdf", "PDF · 5 стр"],
      ["power_table.xlsx", "XLSX · 9 типов"],
      ["MEP_Light_2026.txt", "ФОП · 302 параметра"],
    ],
    parameters: [
      ["ADSK_Наименование", "Text", "Shared"],
      ["Мощность", "Electrical Power", "Shared"],
      ["Световой поток", "Number", "Shared"],
      ["Длина", "Length", "Family"],
      ["IES файл", "Text", "Family"],
    ],
    types: [
      ["LINE 600 18W", "600", "80", "45", "18W"],
      ["LINE 1200 36W", "1200", "80", "45", "36W"],
      ["LINE 1500 48W", "1500", "80", "45", "48W"],
    ],
    checks: [
      ["warn", "Исходники", "IES-файл отсутствует"],
      ["pass", "Параметры", "9 обязательных параметров найдены"],
      ["warn", "Типы", "Нужно проверить световой поток"],
      ["pass", "Категория", "Lighting Fixtures совпадает"],
    ],
    risks: [
      ["M", "medium", "Фотометрия", "Без IES проверка световых характеристик неполная."],
      ["L", "low", "Типы", "Нужна сверка мощности и длины для 2 строк."],
    ],
    actions: [
      ["upload", "Запросить IES", "Добавить недостающий источник к заданию"],
      ["table-2", "Сверить таблицу", "Проверить 9 типов по XLSX"],
      ["plug", "Открыть в Revit", "Продолжить реализацию семейства"],
    ],
  },
  {
    id: "FAM-0235",
    title: "Воздухораспределитель круглый",
    category: "ОВиК",
    owner: "Мария Орлова",
    due: "21 июн",
    fop: "HVAC_2026",
    status: "blocked",
    statusText: "Ожидает данных",
    score: "48%",
    aiSummary:
      "Задание содержит противоречие между таблицей диаметров и PDF-каталогом. Требуется подтверждение линейки типоразмеров.",
    sources: [
      ["air_diffuser_task.pdf", "PDF · 3 стр"],
      ["diameters.xlsx", "XLSX · 11 строк"],
      ["catalog_fragment.png", "PNG · референс"],
    ],
    parameters: [
      ["ADSK_Наименование", "Text", "Shared"],
      ["Диаметр", "Length", "Family"],
      ["Расход воздуха", "Number", "Shared"],
      ["Материал", "Material", "Family"],
    ],
    types: [
      ["DIF 100", "100", "60", "35", "сталь"],
      ["DIF 125", "125", "70", "35", "сталь"],
      ["DIF 160", "160", "85", "40", "сталь"],
    ],
    checks: [
      ["fail", "Типоразмеры", "PDF и XLSX расходятся по диаметру 200"],
      ["warn", "ФОП", "Параметр расхода не найден в активном профиле"],
      ["pass", "Категория", "Air Terminals совпадает"],
    ],
    risks: [
      ["H", "high", "Типоразмеры", "Нельзя создавать типы до подтверждения таблицы."],
      ["M", "medium", "ФОП", "Нужен shared parameter для расхода воздуха."],
    ],
    actions: [
      ["message-square-warning", "Задать вопрос", "Уточнить диаметр 200 у BIM-менеджера"],
      ["file-key-2", "Обновить ФОП", "Добавить или сопоставить параметр расхода"],
      ["pause", "Приостановить", "Оставить задание до подтверждения"],
    ],
  },
];

const catalogItems = [
  {
    id: "CAT-0148",
    name: "Шкаф архивный металлический",
    category: "Мебель",
    version: "v1.4",
    status: "Актуально",
    statusKind: "ready",
    downloads: "428 скачиваний",
    updated: "24 мая",
    author: "BIM Library",
    size: "1.8 MB",
    revit: "2023-2025",
    tags: ["мебель", "металл", "типоразмеры"],
    description: "Параметрическое семейство архивного шкафа с материалами корпуса, фасада и ручек.",
    parameters: ["ADSK_Наименование", "ADSK_Код изделия", "Ширина", "Высота", "Глубина", "Материал корпуса"],
    versions: [
      ["v1.4", "Актуальная", "Исправлены материалы фасадов"],
      ["v1.3", "Архив", "Добавлены 6 типоразмеров"],
      ["v1.2", "Архив", "Первичная приемка"],
    ],
    checks: [
      ["pass", "ФОП", "Все обязательные shared parameters найдены"],
      ["pass", "Типы", "6 типоразмеров опубликованы"],
      ["pass", "Размер файла", "1.8 MB, в пределах нормы"],
    ],
  },
  {
    id: "CAT-0162",
    name: "Дверь техническая EI60",
    category: "Двери",
    version: "v2.1",
    status: "Требует ревизии",
    statusKind: "review",
    downloads: "96 скачиваний",
    updated: "19 мая",
    author: "Fire Safety Pack",
    size: "3.4 MB",
    revit: "2024-2025",
    tags: ["двери", "EI60", "огнестойкость"],
    description: "Техническая дверь с наборами типоразмеров, направлением открывания и параметрами огнестойкости.",
    parameters: ["ADSK_Класс огнестойкости", "Ширина проема", "Высота проема", "Толщина полотна"],
    versions: [
      ["v2.1", "Актуальная", "Обновлены типы EI60"],
      ["v2.0", "Архив", "Перевод на DoorPack_2026"],
      ["v1.8", "Архив", "Исправлены классификаторы"],
    ],
    checks: [
      ["warn", "Классификатор", "4 типа требуют проверки кода изделия"],
      ["pass", "Категория", "Doors совпадает"],
      ["pass", "Размер файла", "3.4 MB, в пределах нормы"],
    ],
  },
  {
    id: "CAT-0190",
    name: "Светильник линейный подвесной",
    category: "Освещение",
    version: "v1.2",
    status: "Актуально",
    statusKind: "ready",
    downloads: "214 скачиваний",
    updated: "8 мая",
    author: "MEP Library",
    size: "2.2 MB",
    revit: "2023-2025",
    tags: ["освещение", "MEP", "IES"],
    description: "Линейный подвесной светильник с мощностью, световым потоком и типоразмерами длины.",
    parameters: ["Мощность", "Световой поток", "Длина", "IES файл"],
    versions: [
      ["v1.2", "Актуальная", "Добавлены IES references"],
      ["v1.1", "Архив", "Обновлена таблица мощностей"],
      ["v1.0", "Архив", "Публикация MVP"],
    ],
    checks: [
      ["pass", "Параметры", "9 обязательных параметров найдены"],
      ["warn", "IES", "2 типа требуют сверки фотометрии"],
      ["pass", "Категория", "Lighting Fixtures совпадает"],
    ],
  },
  {
    id: "CAT-0215",
    name: "Диффузор круглый D100-D250",
    category: "ОВиК",
    version: "v3.0",
    status: "Устаревает",
    statusKind: "blocked",
    downloads: "182 скачивания",
    updated: "2 апр",
    author: "HVAC Library",
    size: "1.2 MB",
    revit: "2022-2024",
    tags: ["ОВиК", "диффузор", "воздух"],
    description: "Круглый воздухораспределитель с диаметрами D100-D250 и параметрами расхода воздуха.",
    parameters: ["Диаметр", "Расход воздуха", "Материал", "ADSK_Наименование"],
    versions: [
      ["v3.0", "Актуальная", "Старая версия ФОП"],
      ["v2.8", "Архив", "Добавлен D250"],
      ["v2.4", "Архив", "Исправлены материалы"],
    ],
    checks: [
      ["fail", "ФОП", "Нужна миграция на HVAC_2026"],
      ["warn", "Совместимость", "Нет версии для Revit 2025"],
      ["pass", "Типы", "11 типоразмеров опубликованы"],
    ],
  },
];

const state = {
  view: "tasks",
  selectedTaskId: tasks[0].id,
  selectedCatalogId: catalogItems[0].id,
  selectedTab: "sources",
  filter: "all",
  search: "",
};

const statusClass = {
  ready: "ready",
  dev: "dev",
  review: "review",
  blocked: "blocked",
};

const taskList = document.querySelector("#taskList");
const tabContent = document.querySelector("#tabContent");
const workspace = document.querySelector(".workspace");

function selectedTask() {
  return tasks.find((task) => task.id === state.selectedTaskId) || tasks[0];
}

function selectedCatalogItem() {
  return catalogItems.find((item) => item.id === state.selectedCatalogId) || catalogItems[0];
}

function renderApp() {
  document
    .querySelectorAll("[data-view]")
    .forEach((button) => button.classList.toggle("is-active", button.dataset.view === state.view));

  if (state.view === "catalog") {
    renderCatalogWorkspace();
  } else {
    renderTaskWorkspace();
  }

  refreshIcons();
}

function renderTaskWorkspace() {
  workspace.innerHTML = `
    <header class="topbar">
      <div>
        <p class="eyebrow">Разработка семейств</p>
        <h1>Реестр заданий</h1>
      </div>
      <div class="topbar-actions">
        <label class="search-field">
          <i data-lucide="search"></i>
          <input id="globalSearch" type="search" placeholder="Поиск задания, семейства, параметра" value="${state.search}" />
        </label>
        <button class="icon-button" type="button" title="Уведомления" aria-label="Уведомления">
          <i data-lucide="bell"></i>
        </button>
        <button class="primary-button" type="button">
          <i data-lucide="plus"></i>
          <span>Задание</span>
        </button>
      </div>
    </header>

    <section class="metrics-grid" aria-label="Сводка">
      <article class="metric">
        <div class="metric-label">Готово к разработке</div>
        <div class="metric-value">9</div>
        <div class="metric-trend positive">+3 за неделю</div>
      </article>
      <article class="metric">
        <div class="metric-label">На AI-разборе</div>
        <div class="metric-value">6</div>
        <div class="metric-trend neutral">среднее 4 мин</div>
      </article>
      <article class="metric">
        <div class="metric-label">На проверке</div>
        <div class="metric-value">12</div>
        <div class="metric-trend warning">5 с замечаниями</div>
      </article>
      <article class="metric">
        <div class="metric-label">В каталоге</div>
        <div class="metric-value">428</div>
        <div class="metric-trend positive">94% актуальны</div>
      </article>
    </section>

    <section class="work-grid">
      <section class="task-column" aria-label="Список заданий">
        <div class="section-head">
          <h2>Очередь</h2>
          <div class="segmented" role="group" aria-label="Фильтр статуса">
            <button class="${state.filter === "all" ? "is-selected" : ""}" type="button" data-filter="all">Все</button>
            <button class="${state.filter === "in_development" ? "is-selected" : ""}" type="button" data-filter="in_development">В работе</button>
            <button class="${state.filter === "review" ? "is-selected" : ""}" type="button" data-filter="review">Проверка</button>
          </div>
        </div>
        <div id="taskList" class="task-list"></div>
      </section>

      <section class="detail-column" aria-label="Карточка задания">
        <div class="detail-header">
          <div>
            <div id="taskNumber" class="record-number"></div>
            <h2 id="taskTitle"></h2>
          </div>
          <div class="detail-actions">
            <span id="taskStatus" class="status-pill"></span>
            <button class="icon-button" type="button" title="Открыть в Revit" aria-label="Открыть в Revit">
              <i data-lucide="external-link"></i>
            </button>
          </div>
        </div>

        <div class="detail-meta">
          <div>
            <span>Категория</span>
            <strong id="taskCategory"></strong>
          </div>
          <div>
            <span>Исполнитель</span>
            <strong id="taskOwner"></strong>
          </div>
          <div>
            <span>Срок</span>
            <strong id="taskDue"></strong>
          </div>
          <div>
            <span>Версия ФОП</span>
            <strong id="taskFop"></strong>
          </div>
        </div>

        <div class="tabs" role="tablist" aria-label="Данные задания">
          <button class="${state.selectedTab === "sources" ? "is-active" : ""}" type="button" data-tab="sources">Исходники</button>
          <button class="${state.selectedTab === "spec" ? "is-active" : ""}" type="button" data-tab="spec">Спецификация</button>
          <button class="${state.selectedTab === "checks" ? "is-active" : ""}" type="button" data-tab="checks">Проверка</button>
          <button class="${state.selectedTab === "catalog" ? "is-active" : ""}" type="button" data-tab="catalog">Каталог</button>
        </div>

        <div id="tabContent" class="tab-content"></div>
      </section>

      <aside class="inspector" aria-label="AI-инспектор">
        <div class="inspector-head">
          <div>
            <p class="eyebrow">AI-инспектор</p>
            <h2 id="aiScore"></h2>
          </div>
          <button class="icon-button" type="button" title="Обновить разбор" aria-label="Обновить разбор">
            <i data-lucide="refresh-cw"></i>
          </button>
        </div>

        <div class="ai-summary" id="aiSummary"></div>

        <div class="inspector-block">
          <h3>Риски</h3>
          <div id="riskList" class="risk-list"></div>
        </div>

        <div class="inspector-block">
          <h3>Следующие действия</h3>
          <div id="nextActions" class="action-list"></div>
        </div>
      </aside>
    </section>
  `;

  renderTasks();
  renderDetails();
}

function renderTasks() {
  const query = state.search.trim().toLowerCase();
  const filtered = tasks.filter((task) => {
    const matchesFilter =
      state.filter === "all" ||
      (state.filter === "in_development" && task.status === "dev") ||
      (state.filter === "review" && task.status === "review");
    const matchesSearch = `${task.id} ${task.title} ${task.category} ${task.owner}`
      .toLowerCase()
      .includes(query);

    return matchesFilter && matchesSearch;
  });

  document.querySelector("#taskList").innerHTML = filtered
    .map(
      (task) => `
      <button class="task-card ${task.id === state.selectedTaskId ? "is-active" : ""}" type="button" data-task-id="${task.id}">
        <div class="task-card-top">
          <span class="task-code">${task.id}</span>
          <span class="badge ${statusClass[task.status]}">${task.statusText}</span>
        </div>
        <div class="task-card-title">${task.title}</div>
        <div class="task-card-meta">
          <span>${task.category}</span>
          <span>${task.due}</span>
        </div>
      </button>
    `,
    )
    .join("");

  if (!filtered.length) {
    document.querySelector("#taskList").innerHTML = `<div class="empty-state">Ничего не найдено</div>`;
  }
}

function renderDetails() {
  const task = selectedTask();

  document.querySelector("#taskNumber").textContent = task.id;
  document.querySelector("#taskTitle").textContent = task.title;
  document.querySelector("#taskCategory").textContent = task.category;
  document.querySelector("#taskOwner").textContent = task.owner;
  document.querySelector("#taskDue").textContent = task.due;
  document.querySelector("#taskFop").textContent = task.fop;

  const status = document.querySelector("#taskStatus");
  status.textContent = task.statusText;
  status.className = `status-pill ${statusClass[task.status]}`;

  document.querySelector("#aiScore").textContent = `Готовность ${task.score}`;
  document.querySelector("#aiSummary").textContent = task.aiSummary;

  renderRisks(task);
  renderActions(task);
  renderTab(task);
  refreshIcons();
}

function renderRisks(task) {
  document.querySelector("#riskList").innerHTML = task.risks
    .map(
      ([letter, level, title, text]) => `
      <div class="risk-item">
        <span class="risk-level ${level}">${letter}</span>
        <div>
          <strong>${title}</strong>
          <span>${text}</span>
        </div>
      </div>
    `,
    )
    .join("");
}

function renderActions(task) {
  document.querySelector("#nextActions").innerHTML = task.actions
    .map(
      ([icon, title, text]) => `
      <button class="action-item" type="button">
        <span class="action-icon"><i data-lucide="${icon}"></i></span>
        <div>
          <strong>${title}</strong>
          <span>${text}</span>
        </div>
      </button>
    `,
    )
    .join("");
}

function renderTab(task) {
  const templates = {
    sources: renderSources,
    spec: renderSpec,
    checks: renderChecks,
    catalog: renderCatalog,
  };

  document.querySelector("#tabContent").innerHTML = templates[state.selectedTab](task);
}

function renderSources(task) {
  return `
    <div class="panel-grid">
      <section class="content-panel">
        <h3>Пакет задания</h3>
        <div class="source-list">
          ${task.sources
            .map(
              ([name, meta]) => `
            <div class="source-row">
              <div class="source-row-main">
                <strong>${name}</strong>
                <span>${meta}</span>
              </div>
              <button class="icon-button" type="button" title="Открыть файл" aria-label="Открыть файл">
                <i data-lucide="file-search"></i>
              </button>
            </div>
          `,
            )
            .join("")}
        </div>
      </section>
      <section class="content-panel">
        <h3>AI-разбор</h3>
        <div class="check-list">
          <div class="check-row">
            <span class="check-icon pass"><i data-lucide="check"></i></span>
            <div class="check-copy">
              <strong>Категория определена</strong>
              <span>${task.category}</span>
            </div>
          </div>
          <div class="check-row">
            <span class="check-icon ${task.status === "blocked" ? "fail" : "pass"}"><i data-lucide="${task.status === "blocked" ? "x" : "check"}"></i></span>
            <div class="check-copy">
              <strong>Типоразмеры извлечены</strong>
              <span>${task.types.length} строки в текущей спецификации</span>
            </div>
          </div>
          <div class="check-row">
            <span class="check-icon warn"><i data-lucide="triangle-alert"></i></span>
            <div class="check-copy">
              <strong>Требует внимания</strong>
              <span>${task.risks[0][2]}</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderSpec(task) {
  return `
    <div class="panel-grid">
      <section class="content-panel">
        <h3>Параметры</h3>
        <div class="parameter-list">
          ${task.parameters
            .map(
              ([name, type, kind]) => `
            <div class="parameter-row">
              <strong>${name}</strong>
              <span class="parameter-kind">${type}</span>
              <span class="badge ${kind === "Shared" ? "ready" : "dev"}">${kind}</span>
            </div>
          `,
            )
            .join("")}
        </div>
      </section>
      <section class="content-panel">
        <h3>Готовность спецификации</h3>
        <div class="source-list">
          <div>
            <div class="progress-shell">
              <div class="progress-bar" style="width: ${task.score}"></div>
            </div>
          </div>
          <div class="check-row">
            <span class="check-icon pass"><i data-lucide="file-key-2"></i></span>
            <div class="check-copy">
              <strong>${task.fop}</strong>
              <span>Активный профиль параметров</span>
            </div>
          </div>
          <div class="check-row">
            <span class="check-icon warn"><i data-lucide="clipboard-pen"></i></span>
            <div class="check-copy">
              <strong>Чеклист приемки</strong>
              <span>${task.checks.length} пункта в текущем наборе</span>
            </div>
          </div>
        </div>
      </section>
      <section class="content-panel full">
        <h3>Типоразмеры</h3>
        <div class="type-table">
          <table>
            <thead>
              <tr>
                <th>Тип</th>
                <th>Ширина</th>
                <th>Глубина</th>
                <th>Высота</th>
                <th>Материал / значение</th>
              </tr>
            </thead>
            <tbody>
              ${task.types
                .map(
                  (row) => `
                <tr>
                  ${row.map((cell) => `<td>${cell}</td>`).join("")}
                </tr>
              `,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  `;
}

function renderChecks(task) {
  return `
    <div class="panel-grid">
      <section class="content-panel full">
        <h3>Отчет проверки</h3>
        <div class="check-list">
          ${task.checks
            .map(
              ([stateName, title, text]) => `
            <div class="check-row">
              <span class="check-icon ${stateName}">
                <i data-lucide="${stateName === "pass" ? "check" : stateName === "warn" ? "triangle-alert" : "x"}"></i>
              </span>
              <div class="check-copy">
                <strong>${title}</strong>
                <span>${text}</span>
              </div>
              <button class="compact-button" type="button">
                <i data-lucide="arrow-right"></i>
              </button>
            </div>
          `,
            )
            .join("")}
        </div>
      </section>
    </div>
  `;
}

function renderCatalog(task) {
  return `
    <div class="panel-grid">
      <section class="content-panel full">
        <h3>Ближайшие семейства</h3>
        <div class="catalog-list">
          ${catalogItems
            .map(
              ({ name, category, version, downloads }) => `
            <div class="catalog-row">
              <div class="catalog-main">
                <strong>${name}</strong>
                <span>${category} · ${version} · ${downloads}</span>
              </div>
              <button class="compact-button" type="button">
                <i data-lucide="${name === task.title ? "git-compare-arrows" : "download"}"></i>
                <span>${name === task.title ? "Сравнить" : "Скачать"}</span>
              </button>
            </div>
          `,
            )
            .join("")}
        </div>
      </section>
    </div>
  `;
}

function refreshIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function renderCatalogWorkspace() {
  const item = selectedCatalogItem();
  const query = state.search.trim().toLowerCase();
  const filtered = catalogItems.filter((catalogItem) =>
    `${catalogItem.id} ${catalogItem.name} ${catalogItem.category} ${catalogItem.tags.join(" ")}`
      .toLowerCase()
      .includes(query),
  );

  workspace.innerHTML = `
    <header class="topbar">
      <div>
        <p class="eyebrow">Внутренняя библиотека</p>
        <h1>Каталог семейств</h1>
      </div>
      <div class="topbar-actions">
        <label class="search-field">
          <i data-lucide="search"></i>
          <input id="globalSearch" type="search" placeholder="Поиск семейства, категории, тега" value="${state.search}" />
        </label>
        <button class="icon-button" type="button" title="Импорт RFA" aria-label="Импорт RFA">
          <i data-lucide="upload"></i>
        </button>
        <button class="primary-button" type="button">
          <i data-lucide="download"></i>
          <span>Скачать</span>
        </button>
      </div>
    </header>

    <section class="metrics-grid" aria-label="Сводка каталога">
      <article class="metric">
        <div class="metric-label">Опубликовано</div>
        <div class="metric-value">428</div>
        <div class="metric-trend positive">94% актуальны</div>
      </article>
      <article class="metric">
        <div class="metric-label">Требуют ревизии</div>
        <div class="metric-value">26</div>
        <div class="metric-trend warning">после смены ФОП</div>
      </article>
      <article class="metric">
        <div class="metric-label">Категории</div>
        <div class="metric-value">18</div>
        <div class="metric-trend neutral">MEP, двери, мебель</div>
      </article>
      <article class="metric">
        <div class="metric-label">Скачивания</div>
        <div class="metric-value">3.8k</div>
        <div class="metric-trend positive">за квартал</div>
      </article>
    </section>

    <section class="catalog-work-grid">
      <section class="task-column" aria-label="Список семейств">
        <div class="section-head">
          <h2>Семейства</h2>
          <div class="segmented" role="group" aria-label="Фильтр каталога">
            <button class="is-selected" type="button">Все</button>
            <button type="button">Актуальные</button>
            <button type="button">Ревизия</button>
          </div>
        </div>
        <div class="task-list">
          ${
            filtered.length
              ? filtered
                  .map(
                    (catalogItem) => `
            <button class="catalog-card ${catalogItem.id === item.id ? "is-active" : ""}" type="button" data-catalog-id="${catalogItem.id}">
              <div class="task-card-top">
                <span class="task-code">${catalogItem.id}</span>
                <span class="badge ${catalogItem.statusKind}">${catalogItem.status}</span>
              </div>
              <div class="task-card-title">${catalogItem.name}</div>
              <div class="task-card-meta">
                <span>${catalogItem.category}</span>
                <span>${catalogItem.version}</span>
              </div>
            </button>
          `,
                  )
                  .join("")
              : `<div class="empty-state">Ничего не найдено</div>`
          }
        </div>
      </section>

      <section class="detail-column" aria-label="Карточка семейства">
        <div class="detail-header">
          <div>
            <div class="record-number">${item.id}</div>
            <h2>${item.name}</h2>
          </div>
          <div class="detail-actions">
            <span class="status-pill ${item.statusKind}">${item.status}</span>
            <button class="icon-button" type="button" title="Скачать RFA" aria-label="Скачать RFA">
              <i data-lucide="download"></i>
            </button>
          </div>
        </div>

        <div class="detail-meta">
          <div>
            <span>Категория</span>
            <strong>${item.category}</strong>
          </div>
          <div>
            <span>Версия</span>
            <strong>${item.version}</strong>
          </div>
          <div>
            <span>Revit</span>
            <strong>${item.revit}</strong>
          </div>
          <div>
            <span>Размер</span>
            <strong>${item.size}</strong>
          </div>
        </div>

        <div class="catalog-detail">
          <section class="content-panel full">
            <h3>Описание</h3>
            <p class="body-copy">${item.description}</p>
            <div class="tag-row">
              ${item.tags.map((tag) => `<span>${tag}</span>`).join("")}
            </div>
          </section>

          <section class="content-panel">
            <h3>Параметры</h3>
            <div class="parameter-list">
              ${item.parameters
                .map(
                  (parameter) => `
                <div class="source-row">
                  <div class="source-row-main">
                    <strong>${parameter}</strong>
                    <span>Доступен в текущей версии</span>
                  </div>
                </div>
              `,
                )
                .join("")}
            </div>
          </section>

          <section class="content-panel">
            <h3>Проверки</h3>
            <div class="check-list">
              ${item.checks
                .map(
                  ([stateName, title, text]) => `
                <div class="check-row">
                  <span class="check-icon ${stateName}">
                    <i data-lucide="${stateName === "pass" ? "check" : stateName === "warn" ? "triangle-alert" : "x"}"></i>
                  </span>
                  <div class="check-copy">
                    <strong>${title}</strong>
                    <span>${text}</span>
                  </div>
                </div>
              `,
                )
                .join("")}
            </div>
          </section>

          <section class="content-panel full">
            <h3>Версии</h3>
            <div class="type-table">
              <table>
                <thead>
                  <tr>
                    <th>Версия</th>
                    <th>Статус</th>
                    <th>Изменения</th>
                    <th>Действие</th>
                  </tr>
                </thead>
                <tbody>
                  ${item.versions
                    .map(
                      ([version, status, note]) => `
                    <tr>
                      <td>${version}</td>
                      <td>${status}</td>
                      <td>${note}</td>
                      <td><button class="compact-button" type="button"><i data-lucide="download"></i><span>RFA</span></button></td>
                    </tr>
                  `,
                    )
                    .join("")}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </section>

      <aside class="inspector" aria-label="Каталог-инспектор">
        <div class="inspector-head">
          <div>
            <p class="eyebrow">Каталог</p>
            <h2>${item.downloads}</h2>
          </div>
          <button class="icon-button" type="button" title="Создать задание на обновление" aria-label="Создать задание на обновление">
            <i data-lucide="clipboard-plus"></i>
          </button>
        </div>

        <div class="ai-summary">
          Последнее обновление: ${item.updated}. Владелец: ${item.author}. Для изменения опубликованного семейства создается отдельное задание с новой приемкой.
        </div>

        <div class="inspector-block">
          <h3>Действия</h3>
          <div class="action-list">
            <button class="action-item" type="button">
              <span class="action-icon"><i data-lucide="download"></i></span>
              <div>
                <strong>Скачать актуальную RFA</strong>
                <span>${item.version} · ${item.size}</span>
              </div>
            </button>
            <button class="action-item" type="button">
              <span class="action-icon"><i data-lucide="git-compare-arrows"></i></span>
              <div>
                <strong>Сравнить версии</strong>
                <span>Проверить изменения перед обновлением</span>
              </div>
            </button>
            <button class="action-item" type="button">
              <span class="action-icon"><i data-lucide="clipboard-plus"></i></span>
              <div>
                <strong>Задание на обновление</strong>
                <span>Создать task из карточки каталога</span>
              </div>
            </button>
          </div>
        </div>
      </aside>
    </section>
  `;
}

document.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    state.view = viewButton.dataset.view;
    state.search = "";
    renderApp();
    return;
  }

  const taskButton = event.target.closest("[data-task-id]");
  if (taskButton) {
    state.selectedTaskId = taskButton.dataset.taskId;
    renderTasks();
    renderDetails();
  }

  const tabButton = event.target.closest("[data-tab]");
  if (tabButton) {
    state.selectedTab = tabButton.dataset.tab;
    document
      .querySelectorAll(".tabs button")
      .forEach((button) => button.classList.toggle("is-active", button === tabButton));
    renderTab(selectedTask());
    refreshIcons();
  }

  const catalogButton = event.target.closest("[data-catalog-id]");
  if (catalogButton) {
    state.selectedCatalogId = catalogButton.dataset.catalogId;
    renderCatalogWorkspace();
    refreshIcons();
  }

  const filterButton = event.target.closest("[data-filter]");
  if (filterButton) {
    state.filter = filterButton.dataset.filter;
    document
      .querySelectorAll(".segmented button")
      .forEach((button) => button.classList.toggle("is-selected", button === filterButton));
    renderTasks();
  }
});

document.addEventListener("input", (event) => {
  if (event.target.id !== "globalSearch") {
    return;
  }

  state.search = event.target.value;
  if (state.view === "catalog") {
    renderCatalogWorkspace();
  } else {
    renderTasks();
  }
});

renderApp();
