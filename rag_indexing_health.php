<?php
declare(strict_types=1);

$updatedAt = '25.05.2026';

function e($value): string
{
    return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function fmt($value): string
{
    if (is_numeric($value)) {
        return number_format((float)$value, 0, ',', ' ');
    }
    return (string)$value;
}

function readLocalHealth(): ?array
{
    if (!isset($_GET['live']) || $_GET['live'] === '0') {
        return null;
    }

    $context = stream_context_create([
        'http' => [
            'timeout' => 0.35,
            'ignore_errors' => true,
        ],
    ]);
    $raw = @file_get_contents('http://127.0.0.1:8050/api/health', false, $context);
    if ($raw === false || $raw === '') {
        return null;
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

$health = readLocalHealth();
$totals = $health['rag']['totals'] ?? [];
$qdrant = $health['rag']['qdrant'] ?? [];

$indexedFiles = $totals['indexed_files'] ?? 795;
$pendingFiles = $totals['pending_files'] ?? 6;
$errorFiles = $totals['error_files'] ?? 0;
$chunks = $totals['chunks'] ?? 260918;
$points = $qdrant['points'] ?? 260918;
$pointsMatch = $qdrant['points_match_sqlite_chunks'] ?? true;

$stats = [
    [
        'value' => fmt($indexedFiles),
        'label' => 'файлов уже в индексе',
        'note' => 'корпус почти собран, без полного reindex',
    ],
    [
        'value' => fmt($pendingFiles),
        'label' => 'файлов осталось',
        'note' => 'последний хвост в NTD_GENERAL_Index',
    ],
    [
        'value' => fmt($errorFiles),
        'label' => 'ошибок в текущем срезе',
        'note' => 'ошибка теперь должна быть файлом, причиной и действием',
    ],
    [
        'value' => fmt($chunks),
        'label' => 'chunks в SQLite',
        'note' => 'metadata ledger держит историю корпуса',
    ],
    [
        'value' => fmt($points),
        'label' => 'points в Qdrant',
        'note' => $pointsMatch ? 'Qdrant совпадает с SQLite' : 'нужно сверить Qdrant и SQLite',
    ],
];

$lessons = [
    [
        'tag' => '01',
        'title' => 'Индексация - это смена на производстве',
        'body' => 'Большой RAG-корпус нельзя собирать как разовую команду. Нужны очередь, приоритеты, статусы, health-checks, безопасные повторы и уважение к уже созданному индексу.',
    ],
    [
        'tag' => '02',
        'title' => 'Docker оказался риском, а не фундаментом',
        'body' => 'Падения контейнерного слоя мешали понимать, где настоящая проблема: в Qdrant, MLX, proxy, памяти или Docker Desktop. Вынос runtime на host сделал систему прозрачнее.',
    ],
    [
        'tag' => '03',
        'title' => 'Главный bottleneck - embeddings',
        'body' => 'Конвертация, chunking, upsert и SQLite занимали мало относительно embed_sec. Поэтому ускорение надо искать в batch size, cache, chunk profiles и качестве embedding-пути.',
    ],
    [
        'tag' => '04',
        'title' => 'Parquet - не украшение, а второй контур смысла',
        'body' => 'Для таблиц RAG не должен притворяться, что строка сметы и абзац норматива одинаковы. Parquet сохраняет row-level структуру, открывает table-aware retrieval и честный SQL-путь.',
    ],
    [
        'tag' => '05',
        'title' => 'PDF - это не формат, а семейство проблем',
        'body' => 'Один PDF может быть текстом, сканом, таблицей, каталогом, приложением или смесью всего сразу. Document Router должен выбирать pipeline, а не гнать все документы одной трубой.',
    ],
    [
        'tag' => '06',
        'title' => 'Умный индекс начинается до LLM',
        'body' => 'Качество ответа рождается в ingestion: структура, домен, тип документа, chunk profile, dataset_filter, terminology filter и проверяемые метаданные важнее красивого prompt-а.',
    ],
];

$pipeline = [
    [
        'name' => 'Document Router',
        'desc' => 'Быстро определяет тип документа и маршрут: markdown, table, pdf tables, OCR marker или mixed pipeline.',
    ],
    [
        'name' => 'Structure-Aware Chunking',
        'desc' => 'Режет не по случайной длине, а по смысловым границам: пункты СП/ГОСТ, заголовки, таблицы, приложения.',
    ],
    [
        'name' => 'Parquet Artifacts',
        'desc' => 'Таблицы получают row-level слой рядом с RAG-чанками: сметы и спецификации можно искать семантически и считать структурно.',
    ],
    [
        'name' => 'Embedding Guard',
        'desc' => 'Контролирует память и swap. Медленный batch лучше, чем быстрый крах и потеря связности индекса.',
    ],
    [
        'name' => 'SQLite Ledger',
        'desc' => 'Хранит состояние файлов, chunks, ошибки, pipeline metadata и связь между исходником и векторным хранилищем.',
    ],
    [
        'name' => 'Qdrant Store',
        'desc' => 'Держит vectors и payload. Его здоровье измеряется совпадением points с chunks в SQLite.',
    ],
];

$principles = [
    'Сначала сохраняем уже построенный индекс, потом ускоряем.',
    'Сначала измеряем bottleneck, потом меняем pipeline.',
    'Сначала делаем ошибку видимой, потом придумываем retry.',
    'Сначала route и metadata, потом LLM.',
    'Сначала baseline golden set, потом hybrid search и reranker.',
];

$timeline = [
    ['label' => 'Старт', 'text' => 'Индексация выглядела как обычная фоновая задача.'],
    ['label' => 'Падения', 'text' => 'Docker начал выпадать из контура, diagnosis стала мутной.'],
    ['label' => 'Разворот', 'text' => 'Qdrant, proxy, MLX, UI и indexer вынесены на host runtime через LaunchAgents.'],
    ['label' => 'Дисциплина', 'text' => 'Indexing mode, memory guard, batch_limit=1, paused chat generation.'],
    ['label' => 'Почти финиш', 'text' => 'SQLite и Qdrant сходятся, pending хвост мал, индекс стал ценным артефактом.'],
    ['label' => 'После нуля', 'text' => 'Snapshot, golden set, K.O.T., hybrid retrieval, table-aware retrieval и Parquet path.'],
];
?>
<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Залог здоровой индексации | RAG</title>
    <meta name="description" content="Что большой прогон RAG-индексации рассказал о Docker, Parquet, Qdrant, embeddings, PDF и здоровой архитектуре индекса.">
    <style>
        :root {
            --bg: #0b0d10;
            --panel: #15191d;
            --panel-2: #1d2328;
            --paper: #f3efe6;
            --ink: #ece7dc;
            --muted: #aeb5b1;
            --line: #334048;
            --cyan: #43c7e8;
            --green: #7ac58b;
            --amber: #d5a245;
            --red: #d66d5c;
            --steel: #8da6b3;
            --shadow: rgba(0, 0, 0, .34);
            --max: 1180px;
        }

        * {
            box-sizing: border-box;
        }

        html {
            scroll-behavior: smooth;
        }

        body {
            margin: 0;
            color: var(--ink);
            background:
                linear-gradient(180deg, rgba(67, 199, 232, .05), transparent 360px),
                var(--bg);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            line-height: 1.65;
            letter-spacing: 0;
        }

        a {
            color: var(--cyan);
            text-decoration: none;
        }

        a:hover {
            text-decoration: underline;
        }

        .page-shell {
            min-height: 100vh;
            overflow: hidden;
        }

        .topbar {
            position: sticky;
            top: 0;
            z-index: 20;
            border-bottom: 1px solid rgba(141, 166, 179, .28);
            background: rgba(11, 13, 16, .88);
            backdrop-filter: blur(14px);
        }

        .topbar-inner {
            width: min(var(--max), calc(100% - 32px));
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            min-height: 64px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
            font-weight: 900;
            letter-spacing: .04em;
            text-transform: uppercase;
        }

        .brand-mark {
            width: 32px;
            height: 32px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 3px;
            padding: 3px;
            border: 1px solid var(--line);
            background: #101418;
        }

        .brand-mark span {
            display: block;
            background: var(--cyan);
        }

        .brand-mark span:nth-child(2),
        .brand-mark span:nth-child(5),
        .brand-mark span:nth-child(8) {
            background: var(--amber);
        }

        .nav {
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 8px;
            font-size: .78rem;
            text-transform: uppercase;
            letter-spacing: .08em;
            color: var(--muted);
        }

        .nav a {
            color: var(--muted);
            padding: 8px 10px;
            border: 1px solid transparent;
        }

        .nav a:hover {
            color: var(--ink);
            border-color: var(--line);
            text-decoration: none;
        }

        .hero {
            width: min(var(--max), calc(100% - 32px));
            margin: 0 auto;
            padding: 76px 0 34px;
            display: grid;
            grid-template-columns: minmax(0, 1.02fr) minmax(360px, .78fr);
            gap: 42px;
            align-items: center;
        }

        .kicker {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            color: var(--cyan);
            font-size: .78rem;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: .16em;
        }

        .kicker::before {
            content: "";
            width: 32px;
            height: 2px;
            background: var(--cyan);
        }

        h1 {
            margin: 18px 0 18px;
            font-size: clamp(2.45rem, 6vw, 5.9rem);
            line-height: .95;
            max-width: 900px;
            letter-spacing: 0;
        }

        .lead {
            max-width: 780px;
            color: var(--muted);
            font-size: clamp(1.05rem, 2vw, 1.36rem);
        }

        .hero-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 28px;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            min-height: 36px;
            border: 1px solid var(--line);
            padding: 7px 11px;
            background: rgba(21, 25, 29, .72);
            color: var(--muted);
            font-size: .82rem;
        }

        .pill strong {
            color: var(--ink);
            margin-right: 6px;
        }

        .hero-visual {
            border: 1px solid var(--line);
            background:
                linear-gradient(90deg, rgba(255, 255, 255, .04) 1px, transparent 1px),
                linear-gradient(180deg, rgba(255, 255, 255, .04) 1px, transparent 1px),
                var(--panel);
            background-size: 28px 28px;
            padding: 22px;
            box-shadow: 0 22px 80px var(--shadow);
        }

        .circuit-title {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            color: var(--muted);
            font-size: .74rem;
            text-transform: uppercase;
            letter-spacing: .12em;
            margin-bottom: 18px;
        }

        .index-map {
            display: grid;
            gap: 12px;
        }

        .index-node {
            display: grid;
            grid-template-columns: 118px 1fr auto;
            gap: 12px;
            align-items: center;
            padding: 12px;
            border: 1px solid rgba(141, 166, 179, .32);
            background: rgba(11, 13, 16, .7);
        }

        .index-node b {
            color: var(--ink);
            font-size: .86rem;
            text-transform: uppercase;
            letter-spacing: .06em;
        }

        .index-node span {
            color: var(--muted);
            font-size: .84rem;
        }

        .signal {
            width: 12px;
            height: 12px;
            background: var(--green);
            box-shadow: 0 0 16px rgba(122, 197, 139, .7);
        }

        .signal.amber {
            background: var(--amber);
            box-shadow: 0 0 16px rgba(213, 162, 69, .65);
        }

        .signal.cyan {
            background: var(--cyan);
            box-shadow: 0 0 16px rgba(67, 199, 232, .65);
        }

        .section {
            border-top: 1px solid rgba(141, 166, 179, .2);
            padding: 72px 0;
        }

        .section.alt {
            background: #101316;
        }

        .section-inner {
            width: min(var(--max), calc(100% - 32px));
            margin: 0 auto;
        }

        .section-head {
            display: grid;
            grid-template-columns: minmax(0, .7fr) minmax(280px, .3fr);
            gap: 36px;
            align-items: end;
            margin-bottom: 28px;
        }

        .section h2 {
            margin: 0;
            font-size: clamp(1.9rem, 4vw, 3.6rem);
            line-height: 1.02;
            letter-spacing: 0;
        }

        .section-copy {
            color: var(--muted);
            margin: 0;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 12px;
        }

        .stat-card,
        .lesson-card,
        .pipeline-step,
        .principle,
        .timeline-item {
            border: 1px solid var(--line);
            background: var(--panel);
            border-radius: 8px;
            box-shadow: 0 12px 34px rgba(0, 0, 0, .18);
        }

        .stat-card {
            padding: 18px;
            min-height: 154px;
        }

        .stat-value {
            color: var(--paper);
            font-weight: 900;
            font-size: clamp(1.8rem, 4vw, 3rem);
            line-height: 1;
        }

        .stat-label {
            margin-top: 12px;
            color: var(--ink);
            font-weight: 800;
            font-size: .92rem;
        }

        .stat-note {
            margin-top: 8px;
            color: var(--muted);
            font-size: .82rem;
            line-height: 1.45;
        }

        .article-grid {
            display: grid;
            grid-template-columns: minmax(0, .68fr) minmax(320px, .32fr);
            gap: 34px;
            align-items: start;
        }

        .article-body {
            color: var(--ink);
            font-size: 1.05rem;
        }

        .article-body p {
            margin: 0 0 20px;
        }

        .article-body h3 {
            margin: 38px 0 14px;
            color: var(--paper);
            font-size: 1.42rem;
            line-height: 1.2;
        }

        .article-body strong {
            color: var(--paper);
        }

        .pullquote {
            margin: 30px 0;
            border-left: 4px solid var(--amber);
            padding: 20px 0 20px 22px;
            color: var(--paper);
            font-size: clamp(1.2rem, 2.5vw, 1.72rem);
            line-height: 1.25;
            font-weight: 800;
        }

        .side-rail {
            display: grid;
            gap: 14px;
            position: sticky;
            top: 88px;
        }

        .side-box {
            border: 1px solid var(--line);
            background: var(--panel-2);
            border-radius: 8px;
            padding: 18px;
        }

        .side-box h3 {
            margin: 0 0 10px;
            font-size: .9rem;
            text-transform: uppercase;
            letter-spacing: .1em;
            color: var(--cyan);
        }

        .side-box p,
        .side-box li {
            color: var(--muted);
            font-size: .92rem;
        }

        .side-box ul {
            margin: 10px 0 0;
            padding-left: 18px;
        }

        .lessons-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 14px;
        }

        .lesson-card {
            padding: 20px;
            min-height: 244px;
        }

        .lesson-tag {
            color: var(--amber);
            font-weight: 900;
            font-size: .8rem;
            letter-spacing: .14em;
        }

        .lesson-card h3 {
            margin: 14px 0 12px;
            font-size: 1.16rem;
            line-height: 1.22;
        }

        .lesson-card p {
            margin: 0;
            color: var(--muted);
            font-size: .94rem;
        }

        .pipeline {
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 10px;
        }

        .pipeline-step {
            padding: 16px;
            min-height: 188px;
            border-top: 3px solid var(--cyan);
        }

        .pipeline-step:nth-child(2n) {
            border-top-color: var(--green);
        }

        .pipeline-step:nth-child(3n) {
            border-top-color: var(--amber);
        }

        .pipeline-step h3 {
            margin: 0 0 12px;
            font-size: .98rem;
            line-height: 1.2;
        }

        .pipeline-step p {
            margin: 0;
            color: var(--muted);
            font-size: .86rem;
            line-height: 1.45;
        }

        .principles {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 12px;
            counter-reset: principles;
        }

        .principle {
            padding: 18px;
            min-height: 168px;
            counter-increment: principles;
        }

        .principle::before {
            content: counter(principles, decimal-leading-zero);
            display: block;
            color: var(--green);
            font-weight: 900;
            letter-spacing: .12em;
            margin-bottom: 18px;
        }

        .principle p {
            margin: 0;
            font-weight: 800;
            line-height: 1.35;
        }

        .timeline {
            display: grid;
            gap: 12px;
        }

        .timeline-item {
            display: grid;
            grid-template-columns: 150px 1fr;
            gap: 20px;
            padding: 18px;
            align-items: start;
        }

        .timeline-item b {
            color: var(--amber);
            text-transform: uppercase;
            letter-spacing: .1em;
            font-size: .8rem;
        }

        .timeline-item p {
            margin: 0;
            color: var(--muted);
        }

        .closing {
            background: var(--paper);
            color: #111417;
            padding: 78px 0;
        }

        .closing .section-inner {
            display: grid;
            grid-template-columns: minmax(0, .65fr) minmax(280px, .35fr);
            gap: 40px;
            align-items: center;
        }

        .closing h2 {
            color: #111417;
            margin: 0 0 18px;
            font-size: clamp(2rem, 5vw, 4.4rem);
            line-height: 1;
        }

        .closing p {
            color: #384047;
            font-size: 1.08rem;
            margin: 0 0 16px;
        }

        .checklist {
            border: 1px solid rgba(17, 20, 23, .22);
            background: rgba(255, 255, 255, .48);
            border-radius: 8px;
            padding: 20px;
        }

        .checklist h3 {
            margin: 0 0 12px;
            text-transform: uppercase;
            letter-spacing: .1em;
            font-size: .82rem;
        }

        .checklist ol {
            margin: 0;
            padding-left: 20px;
        }

        .checklist li {
            margin: 8px 0;
            color: #30373d;
            font-weight: 650;
        }

        .footer {
            border-top: 1px solid rgba(141, 166, 179, .24);
            padding: 28px 0;
            color: var(--muted);
            font-size: .84rem;
        }

        .footer-inner {
            width: min(var(--max), calc(100% - 32px));
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            gap: 20px;
            flex-wrap: wrap;
        }

        code {
            color: var(--paper);
            background: rgba(255, 255, 255, .07);
            border: 1px solid rgba(141, 166, 179, .3);
            padding: .08em .32em;
            border-radius: 4px;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: .92em;
        }

        @media (max-width: 1080px) {
            .hero,
            .section-head,
            .article-grid,
            .closing .section-inner {
                grid-template-columns: 1fr;
            }

            .hero-visual {
                max-width: 680px;
            }

            .stats-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .lessons-grid,
            .pipeline,
            .principles {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .side-rail {
                position: static;
            }
        }

        @media (max-width: 680px) {
            .topbar-inner {
                align-items: flex-start;
                flex-direction: column;
                padding: 14px 0;
            }

            .nav {
                justify-content: flex-start;
            }

            .hero {
                padding-top: 42px;
            }

            .index-node,
            .timeline-item {
                grid-template-columns: 1fr;
            }

            .stats-grid,
            .lessons-grid,
            .pipeline,
            .principles {
                grid-template-columns: 1fr;
            }

            .section {
                padding: 52px 0;
            }
        }
    </style>
</head>
<body>
<div class="page-shell">
    <header class="topbar">
        <div class="topbar-inner">
            <div class="brand" aria-label="RAG индекс">
                <div class="brand-mark" aria-hidden="true">
                    <span></span><span></span><span></span>
                    <span></span><span></span><span></span>
                    <span></span><span></span><span></span>
                </div>
                <span>RAG Index Health</span>
            </div>
            <nav class="nav" aria-label="Разделы статьи">
                <a href="#health">Срез</a>
                <a href="#lessons">Уроки</a>
                <a href="#pipeline">Pipeline</a>
                <a href="#principles">Принципы</a>
            </nav>
        </div>
    </header>

    <main>
        <section class="hero" aria-labelledby="hero-title">
            <div>
                <div class="kicker">после большого прогона</div>
                <h1 id="hero-title">Залог здоровой индексации</h1>
                <p class="lead">
                    Что Л.Е.С. узнал, пока собирал большой RAG-корпус: почему Docker пришлось убрать из критического пути,
                    зачем таблицам Parquet, где на самом деле живет bottleneck, и почему умный индекс начинается задолго до LLM.
                </p>
                <div class="hero-meta">
                    <span class="pill"><strong>Дата</strong><?= e($updatedAt) ?></span>
                    <span class="pill"><strong>Режим</strong><?= $health ? 'live-срез из proxy' : 'статический срез' ?></span>
                    <span class="pill"><strong>Фокус</strong>RAG, Qdrant, MLX, Parquet, indexing mode</span>
                </div>
            </div>

            <aside class="hero-visual" aria-label="Карта здоровой индексации">
                <div class="circuit-title">
                    <span>healthy index circuit</span>
                    <span><?= $pointsMatch ? 'sqlite = qdrant' : 'verify counts' ?></span>
                </div>
                <div class="index-map">
                    <div class="index-node">
                        <b>Sources</b>
                        <span>PDF, DOCX, XLSX, CSV, EML</span>
                        <i class="signal cyan"></i>
                    </div>
                    <div class="index-node">
                        <b>Router</b>
                        <span>pipeline by document type and complexity</span>
                        <i class="signal amber"></i>
                    </div>
                    <div class="index-node">
                        <b>Parquet</b>
                        <span>row-level artifacts for tables and estimates</span>
                        <i class="signal"></i>
                    </div>
                    <div class="index-node">
                        <b>Embeddings</b>
                        <span>main bottleneck, guarded by memory policy</span>
                        <i class="signal amber"></i>
                    </div>
                    <div class="index-node">
                        <b>Qdrant</b>
                        <span><?= e(fmt($points)) ?> points, persistent host runtime</span>
                        <i class="signal"></i>
                    </div>
                </div>
            </aside>
        </section>

        <section class="section" id="health">
            <div class="section-inner">
                <div class="section-head">
                    <h2>Сначала здоровье, потом скорость</h2>
                    <p class="section-copy">
                        Здоровая индексация - это не максимальный throughput любой ценой. Это управляемое движение,
                        где каждый batch оставляет систему в проверяемом состоянии.
                    </p>
                </div>

                <div class="stats-grid">
                    <?php foreach ($stats as $stat): ?>
                        <article class="stat-card">
                            <div class="stat-value"><?= e($stat['value']) ?></div>
                            <div class="stat-label"><?= e($stat['label']) ?></div>
                            <div class="stat-note"><?= e($stat['note']) ?></div>
                        </article>
                    <?php endforeach; ?>
                </div>
            </div>
        </section>

        <section class="section alt">
            <div class="section-inner article-grid">
                <article class="article-body">
                    <p>
                        Большая индексация началась как техническая задача: забрать корпус, распарсить документы,
                        нарезать chunks, получить embeddings и сложить vectors в Qdrant. Но чем дольше шел прогон,
                        тем яснее становилось: индекс - это не файл и не коллекция. Это производственный актив.
                    </p>
                    <p>
                        Актив нельзя пересоздавать от скуки. Его защищают, измеряют, сверяют и только потом ускоряют.
                        Поэтому главный вывод звучит просто: <strong>залог здоровой индексации - наблюдаемость,
                        идемпотентность и уважение к узкому месту</strong>.
                    </p>

                    <div class="pullquote">
                        Умный индекс начинается не в prompt-е. Он начинается там, где документ получает правильный маршрут.
                    </div>

                    <h3>Почему Docker ушел из критического пути</h3>
                    <p>
                        Docker был удобен как стартовая упаковка, но во время долгой локальной индексации стал дополнительной
                        точкой неопределенности. Когда падает контейнерный слой, диагностика смешивает инфраструктуру и
                        прикладную логику: непонятно, умер Qdrant, proxy, сеть, MLX или сам Docker Desktop.
                    </p>
                    <p>
                        Переход на no-Docker host runtime сделал контур честнее. Qdrant, proxy, MLX, UI и indexer стали
                        отдельными LaunchAgent-сервисами. Это проще перезапускать, проще диагностировать и труднее случайно
                        потерять вместе с контейнерной обвязкой.
                    </p>

                    <h3>Почему Parquet нужен рядом с RAG</h3>
                    <p>
                        Таблицы нельзя лечить как обычный текст. Смета, спецификация или КС-2 несут смысл строками,
                        колонками, кодами, количествами и связями. Если все это превратить только в плоский текстовый chunk,
                        RAG увидит слова, но потеряет форму.
                    </p>
                    <p>
                        Parquet дает второй контур: row-level артефакты для таблиц. Семантический поиск может найти нужный
                        фрагмент, а структурный слой - посчитать, отфильтровать, собрать позиции и проверить числа. Это
                        основа table-aware retrieval.
                    </p>

                    <h3>Почему embeddings стали главным счетчиком времени</h3>
                    <p>
                        Логи быстро сняли романтику с предположений. PDF-парсинг, chunking, upsert и SQLite не были главным
                        тормозом. Основное время уходило в <code>embed_sec</code>. Один тяжелый нормативный файл превращался
                        в сотни chunks, и именно embeddings задавали темп всей смене.
                    </p>
                    <p>
                        Поэтому здоровая оптимизация после индексации должна идти не в сторону случайных ускорений, а в
                        сторону benchmark-ов: batch size, chunk profiles, hash-cache, memory pressure, golden retrieval set.
                    </p>

                    <h3>Почему memory guard был прав</h3>
                    <p>
                        Memory guard раздражает ровно до первого случая, когда понимаешь: он остановил не работу, а аварию.
                        На Mac Mini M4 с 24 GB одновременно живут embeddings, MLX, Qdrant, proxy и UI. Если дать всем
                        работать без дисциплины, swap быстро превращает производственный поток в лотерею.
                    </p>
                    <p>
                        Индексация выбрала медленный, но сохранный путь: <code>indexing mode</code>, paused chat generation,
                        conservative batch policy, сверка SQLite/Qdrant и безопасный recovery без удаления данных.
                    </p>
                </article>

                <aside class="side-rail">
                    <section class="side-box">
                        <h3>Формула здоровья</h3>
                        <p>
                            Здоровый индекс - это когда pending уменьшается, errors объяснимы, chunks равны points,
                            recovery не удаляет данные, а UI показывает правду.
                        </p>
                    </section>
                    <section class="side-box">
                        <h3>После pending = 0</h3>
                        <ul>
                            <li>snapshot SQLite и Qdrant;</li>
                            <li>golden retrieval baseline;</li>
                            <li>K.O.T. как настраиваемый terminology filter;</li>
                            <li>hybrid dense+sparse search;</li>
                            <li>table-aware retrieval через Parquet.</li>
                        </ul>
                    </section>
                    <section class="side-box">
                        <h3>Главный запрет</h3>
                        <p>
                            Не делать полный reindex ради эксперимента, пока golden set не доказал, что изменение стоит
                            риска и времени.
                        </p>
                    </section>
                </aside>
            </div>
        </section>

        <section class="section" id="lessons">
            <div class="section-inner">
                <div class="section-head">
                    <h2>Что мы узнали</h2>
                    <p class="section-copy">
                        Эти уроки родились не из архитектурной фантазии, а из сопротивления настоящего прогона.
                    </p>
                </div>
                <div class="lessons-grid">
                    <?php foreach ($lessons as $lesson): ?>
                        <article class="lesson-card">
                            <div class="lesson-tag"><?= e($lesson['tag']) ?></div>
                            <h3><?= e($lesson['title']) ?></h3>
                            <p><?= e($lesson['body']) ?></p>
                        </article>
                    <?php endforeach; ?>
                </div>
            </div>
        </section>

        <section class="section alt" id="pipeline">
            <div class="section-inner">
                <div class="section-head">
                    <h2>Анатомия умного индекса</h2>
                    <p class="section-copy">
                        Не все документы должны идти одной дорогой. Здоровый RAG выбирает маршрут, сохраняет структуру
                        и оставляет след, который можно проверить.
                    </p>
                </div>
                <div class="pipeline">
                    <?php foreach ($pipeline as $step): ?>
                        <article class="pipeline-step">
                            <h3><?= e($step['name']) ?></h3>
                            <p><?= e($step['desc']) ?></p>
                        </article>
                    <?php endforeach; ?>
                </div>
            </div>
        </section>

        <section class="section" id="principles">
            <div class="section-inner">
                <div class="section-head">
                    <h2>Пять правил после этой индексации</h2>
                    <p class="section-copy">
                        Они звучат сухо, но именно они отличают инженерную систему от набора удачных запусков.
                    </p>
                </div>
                <div class="principles">
                    <?php foreach ($principles as $principle): ?>
                        <article class="principle">
                            <p><?= e($principle) ?></p>
                        </article>
                    <?php endforeach; ?>
                </div>
            </div>
        </section>

        <section class="section alt">
            <div class="section-inner">
                <div class="section-head">
                    <h2>Как менялось мышление</h2>
                    <p class="section-copy">
                        В начале мы хотели просто дожать прогон. В конце получили новый стандарт эксплуатации RAG.
                    </p>
                </div>
                <div class="timeline">
                    <?php foreach ($timeline as $item): ?>
                        <article class="timeline-item">
                            <b><?= e($item['label']) ?></b>
                            <p><?= e($item['text']) ?></p>
                        </article>
                    <?php endforeach; ?>
                </div>
            </div>
        </section>

        <section class="closing">
            <div class="section-inner">
                <div>
                    <h2>Индекс надо не только построить. Его надо сохранить здоровым.</h2>
                    <p>
                        После большого прогона главный актив - не скорость и не эффектная диаграмма. Главный актив -
                        связный корпус, где исходники, metadata и vectors сходятся между собой.
                    </p>
                    <p>
                        Именно с этого места начинается следующий этап: качество retrieval, K.O.T., Parquet-aware таблицы,
                        hybrid search и измеряемая модернизация без слепого полного reindex.
                    </p>
                </div>
                <aside class="checklist">
                    <h3>Контрольный лист</h3>
                    <ol>
                        <li>pending_files = 0</li>
                        <li>error_files = 0</li>
                        <li>SQLite chunks = Qdrant points</li>
                        <li>snapshot сделан</li>
                        <li>golden set прогнан</li>
                        <li>chat generation возвращен</li>
                    </ol>
                </aside>
            </div>
        </section>
    </main>

    <footer class="footer">
        <div class="footer-inner">
            <span>RAG Index Health, <?= e($updatedAt) ?></span>
            <span>Static by default. Add <code>?live=1</code> near LES proxy to pull local health.</span>
        </div>
    </footer>
</div>
</body>
</html>
