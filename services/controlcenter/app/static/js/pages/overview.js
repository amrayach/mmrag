/* ---------------------------------------------------------------------------
   overview.js — System Overview: meeting-ready documentation page
   All content is static/hardcoded. No API calls. Works offline.
   Data verified from live DB queries on 2026-05-05 and model evals on 2026-05-06.
   --------------------------------------------------------------------------- */

const Pages = window.Pages || {};

Pages.overview = function(container) {

  // -----------------------------------------------------------------------
  // Section nav IDs
  // -----------------------------------------------------------------------
  const sections = [
    { id: 'ov-hero',       label: 'Overview' },
    { id: 'ov-arch',       label: 'Architecture' },
    { id: 'ov-flow',       label: 'Data Flow' },
    { id: 'ov-components', label: 'Components' },
    { id: 'ov-models',     label: 'AI Models' },
    { id: 'ov-kb',         label: 'Knowledge Base' },
    { id: 'ov-security',   label: 'Security' },
    { id: 'ov-schema',     label: 'Schema' },
    { id: 'ov-demo',       label: 'Demo & Prompts' },
    { id: 'ov-timeline',   label: 'Timeline' },
    { id: 'ov-readiness',  label: 'Readiness' },
    { id: 'ov-limits',     label: 'Limitations' },
    { id: 'ov-discuss',    label: 'Discussion' },
  ];

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  container.innerHTML = `

  <!-- Section nav -->
  <div class="overview-nav" id="ov-nav">
    ${sections.map(s => `<a href="#${s.id}" data-target="${s.id}">${s.label}</a>`).join('')}
  </div>

  <!-- ================================================================== -->
  <!-- S1: Hero / Executive Summary                                       -->
  <!-- ================================================================== -->
  <div class="overview-section overview-hero" id="ov-hero">
    <h1>MMRAG</h1>
    <div class="overview-subtitle">
      <span>Multimodal RAG Demo System</span>
      <span class="overview-badge overview-badge-accent">May 6, 2026</span>
      <span class="overview-badge overview-badge-info">spark-e010.tail907fce.ts.net</span>
    </div>
    <p class="overview-pitch">
      A self-hosted, GPU-accelerated AI system that ingests PDFs and live RSS news feeds,
      understands both text and images, and answers questions with source citations and inline
      images — all streamed token-by-token in real time. Every byte of data stays on the
      DGX Spark server. Optimized for German-language documents with gemma4:26b as the promoted
      text model. Direct RAG Gateway retrieval keeps context assembly fast; n8n orchestrates
      ingestion triggers and fallback workflows.
    </p>
    <div class="metrics-grid" style="margin-top:1.2rem">
      ${Components.metricCard('11', 'Containers', 'var(--success)')}
      ${Components.metricCard('3,931', 'Documents')}
      ${Components.metricCard('15,332', 'Chunks')}
      ${Components.metricCard('3', 'AI Models', 'var(--warning)')}
      ${Components.metricCard('7', 'RSS Feeds', '#5dade2')}
    </div>
  </div>

  <!-- ================================================================== -->
  <!-- S2: Architecture Topology                                          -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-arch">
    <div class="overview-section-title">
      <span class="overview-section-num">02</span> Architecture Topology
    </div>
    <div class="card" style="padding:1.2rem">
      ${_renderArchSVG()}
      <div style="display:flex;gap:1.5rem;justify-content:center;margin-top:0.8rem;font-size:0.72rem;color:var(--text-secondary)">
        <span><svg width="16" height="3" style="vertical-align:middle"><line x1="0" y1="1.5" x2="16" y2="1.5" stroke="#5dade2" stroke-width="2.5"/></svg> Chat Flow</span>
        <span><svg width="16" height="3" style="vertical-align:middle"><line x1="0" y1="1.5" x2="16" y2="1.5" stroke="var(--success)" stroke-width="2.5"/></svg> Ingestion Flow</span>
        <span><svg width="16" height="3" style="vertical-align:middle"><line x1="0" y1="1.5" x2="16" y2="1.5" stroke="var(--border)" stroke-width="1.5" stroke-dasharray="4,3"/></svg> Internal</span>
      </div>
    </div>

    <details class="overview-details" style="margin-top:1rem">
      <summary>Port Map &amp; Access URLs</summary>
      <div class="overview-details-body overview-table-compact">
        <p style="font-size:0.75rem;color:var(--text-secondary);margin-bottom:0.75rem">
          Docker Compose project: <code>ammer-mmragv2</code> &mdash; all containers prefixed <code>ammer_mmragv2_</code>, volumes <code>ammer-mmragv2_</code>, port range <code>56150&ndash;56157</code>.
        </p>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Service</th><th>Container</th><th>Image</th><th>Host Port</th><th>Tailscale</th><th>Internal</th>
            </tr></thead>
            <tbody>
              <tr><td>n8n</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_n8n</td><td><code>n8nio/n8n:1.102.0</code></td><td>56150</td><td><a href="https://spark-e010.tail907fce.ts.net:8450" target="_blank" rel="noopener">:8450</a></td><td>5678</td></tr>
              <tr><td>OpenWebUI</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_openwebui</td><td><code>open-webui (digest)</code></td><td>56151</td><td><a href="https://spark-e010.tail907fce.ts.net:8451" target="_blank" rel="noopener">:8451</a></td><td>8080</td></tr>
              <tr><td>FileBrowser</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_filebrowser</td><td><code>filebrowser:v2.57.1</code></td><td>56152</td><td><a href="https://spark-e010.tail907fce.ts.net:8452" target="_blank" rel="noopener">:8452</a></td><td>80</td></tr>
              <tr><td>Adminer</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_adminer</td><td><code>adminer:5.4.2</code></td><td>56153</td><td><a href="https://spark-e010.tail907fce.ts.net:8453" target="_blank" rel="noopener">:8453</a></td><td>8080</td></tr>
              <tr><td>PostgreSQL</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_postgres</td><td><code>supabase/postgres:15.14.1.081</code></td><td>56154</td><td>&mdash;</td><td>5432</td></tr>
              <tr><td>RAG Gateway</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_rag_gateway</td><td><code>custom build</code></td><td>56155</td><td>&mdash;</td><td>8000</td></tr>
              <tr><td>Control Center</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_controlcenter</td><td><code>custom build</code></td><td>56156</td><td><a href="https://spark-e010.tail907fce.ts.net:8455" target="_blank" rel="noopener">:8455</a></td><td>8000</td></tr>
              <tr><td>Assets</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_assets</td><td><code>nginx:1.29-alpine</code></td><td>56157</td><td><a href="https://spark-e010.tail907fce.ts.net:8454" target="_blank" rel="noopener">:8454</a></td><td>80</td></tr>
              <tr><td>Ollama</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_ollama</td><td><code>ollama/ollama:0.23.1</code></td><td>&mdash;</td><td>&mdash;</td><td>11434</td></tr>
              <tr><td>PDF Ingest</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_pdf_ingest</td><td><code>custom build</code></td><td>&mdash;</td><td>&mdash;</td><td>8001</td></tr>
              <tr><td>RSS Ingest</td><td style="font-family:var(--font-mono);font-size:0.72rem">ammer_mmragv2_rss_ingest</td><td><code>custom build</code></td><td>&mdash;</td><td>&mdash;</td><td>8002</td></tr>
            </tbody>
          </table>
        </div>
        <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.5rem">Host ports bind to <code>127.0.0.1</code> only. Tailnet access is provided by Tailscale Serve, not Compose host bindings. No <code>0.0.0.0</code> public binds.</p>
      </div>
    </details>
  </div>

  <!-- ================================================================== -->
  <!-- S3: Data Flow Deep-Dive                                            -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-flow">
    <div class="overview-section-title">
      <span class="overview-section-num">03</span> Data Flow
    </div>
    <div class="overview-two-col">

      <!-- Chat / Retrieval Flow -->
      <div class="card">
        <div class="card-header"><span class="card-title">Chat / Retrieval</span><span class="badge badge-info">streaming</span></div>
        <div class="overview-flow">
          <div class="overview-flow-step">
            <div class="overview-flow-dot blue">Q</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">User Query</div>
              <div class="overview-flow-desc">OpenWebUI &rarr; POST /v1/chat/completions (stream=true)</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot blue">GW</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">RAG Gateway</div>
              <div class="overview-flow-desc">OpenAI-compatible FastAPI proxy. Direct context mode (78ms).</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot blue">PP</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Query Preprocessing</div>
              <div class="overview-flow-desc">Follow-up rewriting (deictic words: dabei, dazu). @doc / @rss / @pdf filters.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot blue">E</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Embed Query</div>
              <div class="overview-flow-desc">Ollama bge-m3 &rarr; 1024-dim vector</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot blue">VS</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Vector Search</div>
              <div class="overview-flow-desc">pgvector cosine distance &lt; 0.6. Dual retrieval: text (6) + image (2) reserved slots.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot blue">C</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Build Context</div>
              <div class="overview-flow-desc">Image scoring, cross-doc guard, source dedup, system prompt assembly.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot blue">S</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">LLM Streaming</div>
              <div class="overview-flow-desc">Ollama NDJSON &rarr; OpenAI SSE translation. Images + sources appended as final chunk.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot blue">A</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Streamed Answer</div>
              <div class="overview-flow-desc">Token-by-token rendering in OpenWebUI with inline images &amp; citations.</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Ingestion Flow -->
      <div class="card">
        <div class="card-header"><span class="card-title">Ingestion Pipelines</span><span class="badge badge-success">parallel</span></div>

        <div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem">PDF Pipeline</div>
        <div class="overview-flow" style="margin-bottom:1rem">
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">U</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Upload</div>
              <div class="overview-flow-desc">FileBrowser &rarr; data/inbox/ &rarr; file watcher detects (2-poll stability check)</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">T</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Structured Extraction</div>
              <div class="overview-flow-desc">OpenDataLoader PDF 2.4.1 local mode: reading order, headings, tables, images, bounding boxes.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">I</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Chunk + Image Prep</div>
              <div class="overview-flow-desc">Page-bound section chunks with heading paths; tables preserved; images filtered by size/SHA-256 and downscaled.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">V</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Caption + Embed</div>
              <div class="overview-flow-desc">Vision: qwen2.5vl:7b (German). Embed: bge-m3 batch (10/batch). ThreadPool(2) docs.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">DB</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Store</div>
              <div class="overview-flow-desc">pgvector: VECTOR(1024) + HNSW index. Move PDF to processed/.</div>
            </div>
          </div>
        </div>

        <div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem">RSS Pipeline</div>
        <div class="overview-flow">
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">F</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Fetch Feeds</div>
              <div class="overview-flow-desc">7 German feeds (SPIEGEL, Tagesschau, heise, Spektrum, ZDF, DW, FAZ). Every 8h or manual.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">S</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Scrape &amp; Dedup</div>
              <div class="overview-flow-desc">Scrapling with anti-bot fallback. 5-layer dedup: URL, visual, SHA-256, global, file.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">P</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Process</div>
              <div class="overview-flow-desc">Chunk text, caption images, embed. Same bge-m3 model + qwen2.5vl:7b for vision.</div>
            </div>
          </div>
          <div class="overview-flow-step">
            <div class="overview-flow-dot green">DB</div>
            <div class="overview-flow-body">
              <div class="overview-flow-label">Store</div>
              <div class="overview-flow-desc">pgvector with RSS metadata (feed_name, title, url). Images in rss/_shared/.</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ================================================================== -->
  <!-- S4: Component Inventory                                            -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-components">
    <div class="overview-section-title">
      <span class="overview-section-num">04</span> Component Inventory
    </div>
    <div class="card overview-table-compact">
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Service</th><th>Role</th><th>Image</th><th>Host</th><th>TS</th><th>Notes</th>
          </tr></thead>
          <tbody>
            <tr><td><strong>PostgreSQL</strong></td><td>Vector storage + search</td><td><code>supabase/postgres:15.14.1.081</code></td><td>56154</td><td>&mdash;</td><td>pgvector, HNSW index</td></tr>
            <tr><td><strong>Ollama</strong></td><td>GPU inference (text, vision, embed)</td><td><code>ollama/ollama:0.23.1</code></td><td>&mdash;</td><td>&mdash;</td><td>gpus: all, gemma4/bge/qwen2.5vl kept warm</td></tr>
            <tr><td><strong>n8n</strong></td><td>Workflow orchestration</td><td><code>n8nio/n8n:1.102.0</code></td><td>56150</td><td>8450</td><td>Chat Brain, Ingestion Factory, RSS</td></tr>
            <tr><td><strong>RAG Gateway</strong></td><td>OpenAI-compatible streaming proxy</td><td><code>custom (FastAPI)</code></td><td>56155</td><td>&mdash;</td><td>NDJSON &rarr; SSE, direct context</td></tr>
            <tr><td><strong>PDF Ingest</strong></td><td>PDF processing</td><td><code>custom (FastAPI)</code></td><td>&mdash;</td><td>&mdash;</td><td>OpenDataLoader PDF, Java 17, PyMuPDF post-processing, 3 caption workers</td></tr>
            <tr><td><strong>RSS Ingest</strong></td><td>Feed scraping + captioning</td><td><code>custom (FastAPI)</code></td><td>&mdash;</td><td>&mdash;</td><td>Scrapling, 5-layer dedup</td></tr>
            <tr><td><strong>OpenWebUI</strong></td><td>Chat frontend</td><td><code>open-webui (digest-pinned)</code></td><td>56151</td><td>8451</td><td>OpenAI provider &rarr; RAG Gateway</td></tr>
            <tr><td><strong>Control Center</strong></td><td>Admin dashboard (this app)</td><td><code>custom (FastAPI)</code></td><td>56156</td><td>8455</td><td>10 pages, SSE events</td></tr>
            <tr><td><strong>FileBrowser</strong></td><td>PDF upload UI</td><td><code>filebrowser:v2.57.1</code></td><td>56152</td><td>8452</td><td>Serves data/inbox/</td></tr>
            <tr><td><strong>Adminer</strong></td><td>Database admin</td><td><code>adminer:5.4.2</code></td><td>56153</td><td>8453</td><td>PostgreSQL UI</td></tr>
            <tr><td><strong>Assets</strong></td><td>Image serving + gallery</td><td><code>nginx:1.29-alpine</code></td><td>56157</td><td>8454</td><td>Custom gallery UI, JSON autoindex</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ================================================================== -->
  <!-- S5: AI Models                                                      -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-models">
    <div class="overview-section-title">
      <span class="overview-section-num">05</span> AI Models
    </div>
    <div class="card overview-table-compact">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Model</th><th>Type</th><th>Purpose</th><th>Dimensions</th><th>Size</th></tr></thead>
          <tbody>
            <tr>
              <td><code>bge-m3:latest</code></td>
              <td><span class="badge badge-info">Embedding</span></td>
              <td>Multilingual text &amp; caption embeddings</td>
              <td>1024-dim</td>
              <td>1.2 GB</td>
            </tr>
            <tr>
              <td><code>gemma4:26b</code></td>
              <td><span class="badge badge-success">Text Gen</span></td>
              <td>Promoted chat answer model (German output; MoE, 4B active params/token)</td>
              <td>&mdash;</td>
              <td>17 GB disk / ~21 GB VRAM</td>
            </tr>
            <tr>
              <td><code>qwen2.5vl:7b</code></td>
              <td><span class="badge badge-warning">Vision</span></td>
              <td>Image captioning during ingestion</td>
              <td>&mdash;</td>
              <td>6.0 GB</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-top:0.8rem;font-size:0.75rem;color:var(--text-secondary)">
        <span>Total active model footprint: <strong style="color:var(--text-primary)">~28 GB</strong> / 128 GB unified</span>
        <span>OLLAMA_MAX_LOADED_MODELS: <strong style="color:var(--text-primary)">3</strong> (all always loaded)</span>
        <span>OLLAMA_NUM_PARALLEL: <strong style="color:var(--text-primary)">3</strong></span>
      </div>
      <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.4rem">
        Migrated from nomic-embed-text (768d, English-primary) to bge-m3 (1024d, multilingual) on Mar 17.
        Quality score: 2.8 &rarr; 4.3 (+54%). German query accuracy: 20% &rarr; 100%.
        Text-model A/B on May 6 tested seven candidates; gemma4:26b was promoted because it improved answer quality while reducing average total latency from 9.8s to 7.0s versus the 7B baseline.
      </p>
    </div>
  </div>

  <!-- ================================================================== -->
  <!-- S6: Knowledge Base Stats                                           -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-kb">
    <div class="overview-section-title">
      <span class="overview-section-num">06</span> Knowledge Base
    </div>
    <div class="metrics-grid" style="margin-bottom:1rem">
      ${Components.metricCard('3,931', 'Documents')}
      ${Components.metricCard('15,332', 'Total Chunks')}
      ${Components.metricCard('14,223', 'Text Chunks', 'var(--success)')}
      ${Components.metricCard('1,109', 'Image Chunks', 'var(--warning)')}
    </div>

    <div class="overview-two-col">
      <!-- RSS Feed Breakdown -->
      <div class="card">
        <div class="card-header"><span class="card-title">RSS Feeds (3,926 docs / 13,684 chunks)</span></div>
        <div class="overview-table-compact">
          <table>
            <thead><tr><th>Feed</th><th>Docs</th><th>Chunks</th><th></th></tr></thead>
            <tbody>
              ${_feedRow('heise online', 1183, 5028, 5028)}
              ${_feedRow('SPIEGEL', 1526, 3714, 5028)}
              ${_feedRow('Tagesschau', 678, 2092, 5028)}
              ${_feedRow('Spektrum', 284, 1616, 5028)}
              ${_feedRow('ZDF heute', 151, 723, 5028)}
              ${_feedRow('FAZ', 27, 353, 5028)}
              ${_feedRow('Deutsche Welle', 77, 158, 5028)}
            </tbody>
          </table>
        </div>
      </div>

      <!-- PDF Documents -->
      <div class="card">
        <div class="card-header"><span class="card-title">PDF Documents (5 docs / 1,648 chunks)</span></div>
        <div class="overview-table-compact">
          <table>
            <thead><tr><th>Document</th><th>Text</th><th>Images</th><th>Total</th></tr></thead>
            <tbody>
              <tr><td>BMW Group Bericht 2023</td><td>1,297</td><td>45</td><td><strong>1,342</strong></td></tr>
              <tr><td>Nachhaltigkeit bei Siemens</td><td>113</td><td>39</td><td><strong>152</strong></td></tr>
              <tr><td>Siemens Annual Report 2024</td><td>117</td><td>2</td><td><strong>119</strong></td></tr>
              <tr><td>TechVision AG Jahresbericht 2025</td><td>24</td><td>8</td><td><strong>32</strong></td></tr>
              <tr><td>watcher_test.pdf</td><td>3</td><td>0</td><td><strong>3</strong></td></tr>
            </tbody>
          </table>
          <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.5rem">All 1,648 PDF chunks carry OpenDataLoader bounding boxes. BMW has 486 noisy text chunks stored without embeddings and flagged in meta.embedding_error.</p>
        </div>
      </div>
    </div>
  </div>

  <!-- ================================================================== -->
  <!-- S7: Security & Isolation                                           -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-security">
    <div class="overview-section-title">
      <span class="overview-section-num">07</span> Security &amp; Isolation
    </div>
    <div class="overview-checklist-grid">
      ${_checkItem('No Public Bindings', 'Host ports bind only to 127.0.0.1. Tailnet access uses Tailscale Serve, not Compose host bindings.')}
      ${_checkItem('Tailscale Serve Only', 'External access via Tailscale Serve (not Funnel). No public exposure.')}
      ${_checkItem('Isolated Docker Project', 'Unique prefix ammer_mmragv2_* for containers, ammer-mmragv2_ for volumes.')}
      ${_checkItem('Dedicated Port Range', 'Ports 56150\u201356157 reserved. No default ports (5432, 8080) exposed.')}
      ${_checkItem('GPU Isolation', 'Only the Ollama container has GPU access (gpus: all). No GPU outside Docker.')}
      ${_checkItem('Scoped Ingestion Guards', 'Stable-file watcher, submitted-path guard, SHA-256 doc dedup, and rollback-safe asset quarantine.')}
      ${_checkItem('No System Packages', 'Everything containerized. No apt installs. DGX admin guidelines followed.')}
      ${_checkItem('Pinned Image Versions', 'All Docker images version-pinned or digest-pinned in docker-compose.yml.')}
    </div>
  </div>

  <!-- ================================================================== -->
  <!-- S8: Database Schema                                                -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-schema">
    <div class="overview-section-title">
      <span class="overview-section-num">08</span> Database Schema
    </div>
    <details class="overview-details" open>
      <summary>RAG Database Schema (PostgreSQL + pgvector)</summary>
      <div class="overview-details-body overview-schema">
        <p style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.8rem">
          Two databases: <code>n8n</code> (internal workflow state) and <code>rag</code> (application data).
          pgvector extension for cosine similarity search.
        </p>
        <div class="overview-two-col" style="gap:0.75rem">
          <div>
            <div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.3rem">rag_docs</div>
            <pre>doc_id     UUID PRIMARY KEY
filename   TEXT NOT NULL
sha256     TEXT NOT NULL
lang       TEXT DEFAULT 'de'
pages      INT DEFAULT 0
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ</pre>
          </div>
          <div>
            <div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.3rem">rag_chunks</div>
            <pre>id           BIGSERIAL PRIMARY KEY
doc_id       UUID FK &rarr; rag_docs (CASCADE)
chunk_type   TEXT ('text' | 'image')
page         INT
content_text TEXT
caption      TEXT
asset_path   TEXT
embedding    VECTOR(1024)
meta         JSONB</pre>
          </div>
        </div>
        <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.6rem">
          <strong>Indexes:</strong> (doc_id, page), (chunk_type), HNSW (embedding vector_cosine_ops).<br>
          <strong>Re-ingestion:</strong> SHA256 comparison &rarr; if changed, delete all chunks + reprocess.<br>
          <strong>PDF metadata:</strong> <code>meta.bbox</code>, <code>heading_path</code>, <code>page_size</code>, <code>element_type</code>, <code>extractor</code>.<br>
          <strong>Distance threshold:</strong> <code>embedding &lt;=&gt; query &lt; 0.6</code> (cosine distance; score = 1 - distance &gt; 0.4).
        </p>
      </div>
    </details>
  </div>

  <!-- ================================================================== -->
  <!-- S9: Demo Capabilities & Golden Prompts                             -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-demo">
    <div class="overview-section-title">
      <span class="overview-section-num">09</span> Demo Capabilities &amp; Golden Prompts
    </div>

    <div class="overview-capability-grid">
      <div class="overview-capability">
        <div class="overview-capability-icon">&#128196;</div>
        <h4>PDF Analysis</h4>
        <p>Upload PDFs &mdash; structured text, tables, images, heading paths, and bounding boxes are extracted, embedded, and queryable with page references.</p>
      </div>
      <div class="overview-capability" style="border-left-color:var(--success)">
        <div class="overview-capability-icon">&#128225;</div>
        <h4>RSS Live Feeds</h4>
        <p>7 German news feeds auto-ingested every 8h. Cross-reference with documents. Source links in answers.</p>
      </div>
      <div class="overview-capability" style="border-left-color:var(--warning)">
        <div class="overview-capability-icon">&#128444;</div>
        <h4>Multimodal Answers</h4>
        <p>Inline images with AI-generated captions. Vision model describes charts, photos, diagrams.</p>
      </div>
      <div class="overview-capability" style="border-left-color:#5dade2">
        <div class="overview-capability-icon">&#9889;</div>
        <h4>Real-time Streaming</h4>
        <p>Token-by-token via Ollama NDJSON &rarr; OpenAI SSE. Direct context in 78ms (bypasses n8n).</p>
      </div>
    </div>

    <div class="overview-session-label">Session 1 &mdash; Multi-turn (P1&ndash;P4 in one chat)</div>
    ${_promptCard(1, '@TechVision Welche strategischen Megatrends nennt TechVision AG im Jahresbericht 2025? Liste sie vollst\u00e4ndig auf und nenne die Seiten.', ['Deep PDF retrieval'], 'Megatrend overview with page refs, including the strategy diagram')}
    ${_promptCard(2, 'Welche Umsatzentwicklung, Umsatzziele und EBIT-Ziele nennt der Bericht dazu? Nenne konkrete Zahlen und Jahre.', ['Multi-turn follow-up'], '"dazu" triggers context rewriting from P1. 847 Mio 2025, 1.05\u20131.10 Mrd 2026, 1.5 Mrd 2028, EBIT targets')}
    ${_promptCard(3, '@TechVision Welche Nachhaltigkeitsziele und CO\u2082-Reduktionszahlen werden im Bericht genannt?', ['Document scoping'], '@filename restricts search. 42% CO\u2082 reduction, EcoVadis 91/100')}
    ${_promptCard(4, '@TechVision Zeige die wichtigsten Diagramme aus dem Bericht und beschreibe jedes Bild in einem kurzen Satz.', ['Multimodal images'], 'Chart images with cleaned captions (revenue, CO\u2082, tech stack)')}

    <div class="overview-session-label">Session 2 &mdash; Standalone prompts (P5&ndash;P8, new chats)</div>
    ${_promptCard(5, 'Was berichten aktuelle Nachrichten \u00fcber KI, Robotik und industrielle Automatisierung in Deutschland? Fasse maximal vier Punkte mit Quellen zusammen.', ['Live RSS news'], 'Mix of seeded + real articles from spiegel, heise, tagesschau with source links')}
    ${_promptCard(6, 'Vergleiche TechVisions KI-Strategie aus dem Jahresbericht mit aktuellen Nachrichten zu KI, Robotik und industrieller Automatisierung. Nutze PDF- und RSS-Quellen.', ['Cross-source synthesis'], 'PDF + news combined via source-reserved retrieval. Side-by-side analysis of TechVision vs. industry trends')}
    ${_promptCard(7, '@Nachhaltigkeit Welche konkreten Nachhaltigkeitsziele und Ma\u00dfnahmen beschreibt der Siemens-Bericht? Bitte mit Quellenangaben.', ['Structured PDF retrieval'], 'Siemens DEGREE goals, emissions targets, DEI and compliance measures with page refs')}
    ${_promptCard(8, '@BMWGroup Welche Bilder oder Grafiken zeigen Fahrzeuge, Produktionsstandorte oder Personen? Beschreibe sie kurz und nenne die Seitenzahl wenn m\u00f6glich.', ['Real annual report images'], 'BMW image retrieval with realistic caveats, captions and PDF page metadata')}

    <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.8rem">
      Warm response envelope after the gemma4:26b promotion: roughly 3\u201314 seconds in the eval set, with 7.0s average total latency. First query after idle can still be slower if models expired from memory.
    </p>
  </div>

  <!-- ================================================================== -->
  <!-- S10: Engineering Timeline                                          -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-timeline">
    <div class="overview-section-title">
      <span class="overview-section-num">10</span> Engineering Timeline
    </div>
    <details class="overview-details" open>
      <summary>Build History (Feb\u2013May 2026)</summary>
      <div class="overview-details-body">
        <div class="overview-timeline">
          ${_timelineItem('2026-02-17', 'feature', '18-Item Improvement Plan', 'Security hardening, Ollama retry logic, structured logging, German-optimized chunking, connection pooling, Makefile, pinned images.')}
          ${_timelineItem('2026-03-01', 'feature', 'RSS Image Backfill', 'Added /ingest/backfill-images endpoint. 697 RSS image chunks retroactively captioned.')}
          ${_timelineItem('2026-03-04', 'feature', 'Image Relevance + Demo Polish', 'Context-aware captioning, score-based image filtering, dress rehearsal docs, demo readiness script.')}
          ${_timelineItem('2026-03-06', 'feature', 'Parallel PDF Ingestion', 'ThreadPoolExecutor(2) + 3 caption workers + batch embedding. ~8\u20139x speedup.')}
          ${_timelineItem('2026-03-10', 'feature', 'Direct Context Mode', 'Bypassed n8n for retrieval. Latency: 5s \u2192 78ms. Dual retrieval with reserved image slots.')}
          ${_timelineItem('2026-03-16', 'data', 'RSS Image Dedup Overhaul', '5-layer pipeline: URL normalization, visual dedup, SHA-256, global cache, file existence.')}
          ${_timelineItem('2026-03-17', 'fix', 'Demo Hardening', 'Image threshold fix (was no-op), cross-doc guard, feed cleanup 14\u21927, Ollama 0.13.0\u21920.18.0.')}
          ${_timelineItem('2026-03-17', 'migration', 'Embedding Migration', 'nomic-embed-text (768d) \u2192 bge-m3 (1024d). Quality: 2.8\u21924.3 (+54%). Re-embedded 6,088 chunks.')}
          ${_timelineItem('2026-03-18', 'feature', 'TechVision AG Corpus + Review Prep', 'Synthetic German annual report (16p, now 32 chunks after OpenDataLoader reprocess). Demo review agenda. This overview page.')}
          ${_timelineItem('2026-05-05', 'migration', 'OpenDataLoader PDF Upgrade', 'Replaced flat PyMuPDF text chunks with structured PDF extraction. Reprocessed 5 PDFs into 1,648 bbox-enabled chunks.')}
          ${_timelineItem('2026-05-06', 'migration', 'Model A/B + gemma4 Promotion', 'Upgraded Ollama to 0.23.1, tested seven text-model candidates, and promoted gemma4:26b after it beat the 7B baseline on quality and latency.')}
        </div>
      </div>
    </details>
  </div>

  <!-- ================================================================== -->
  <!-- S11: Readiness Assessment                                          -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-readiness">
    <div class="overview-section-title">
      <span class="overview-section-num">11</span> Readiness Assessment
    </div>
    <div class="overview-two-col">
      <div class="card">
        <div class="card-header"><span class="card-title">Demo Readiness Score</span></div>
        <div class="overview-score-hero">
          <svg class="overview-score-ring" viewBox="0 0 36 36">
            <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              fill="none" stroke="var(--bg-tertiary)" stroke-width="3"/>
            <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              fill="none" stroke="var(--accent)" stroke-width="3"
              stroke-dasharray="88, 100" stroke-linecap="round"/>
            <text x="18" y="20" text-anchor="middle" class="overview-score-ring-text" fill="var(--text-primary)">8.8</text>
          </svg>
          <div class="overview-score-summary">
            Weighted across 6 categories. OpenDataLoader ingestion and the gemma4:26b model promotion closed the biggest quality and latency gaps.
            Remaining gaps are BMW brand-list retrieval, click-to-source highlighting, and broader demo-corpus coverage.
          </div>
        </div>
        ${_scoreRow('System Stability', 9.0, 20)}
        ${_scoreRow('Retrieval Quality', 8.2, 20)}
        ${_scoreRow('Architecture', 9.0, 15)}
        ${_scoreRow('Response Speed', 8.6, 15)}
        ${_scoreRow('Presentation', 9.0, 15)}
        ${_scoreRow('Demo Polish', 8.8, 15)}
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Roadmap to 9.0+</span></div>
        <div>
          <div class="overview-roadmap-item">
            <span class="overview-roadmap-impact">+0.4</span>
            <div>
              <div style="font-size:0.82rem;font-weight:600;color:var(--text-primary)">Fix BMW p04 brand-list retrieval</div>
              <div style="font-size:0.72rem;color:var(--text-secondary)">The model A/B showed the list-completeness issue is retrieval-side: the brand-list chunks do not surface in top-k.</div>
            </div>
          </div>
          <div class="overview-roadmap-item">
            <span class="overview-roadmap-impact">+0.4</span>
            <div>
              <div style="font-size:0.82rem;font-weight:600;color:var(--text-primary)">Click-to-source PDF highlights</div>
              <div style="font-size:0.72rem;color:var(--text-secondary)">Use stored page and bbox metadata to highlight the exact cited region in the original PDF.</div>
            </div>
          </div>
          <div class="overview-roadmap-item">
            <span class="overview-roadmap-impact">+0.3</span>
            <div>
              <div style="font-size:0.82rem;font-weight:600;color:var(--text-primary)">Hybrid retrieval or reranking</div>
              <div style="font-size:0.72rem;color:var(--text-secondary)">Add lexical recall or a lightweight reranker for list/table pages where pure vector search misses exact labels.</div>
            </div>
          </div>
          <div class="overview-roadmap-item">
            <span class="overview-roadmap-impact">+0.2</span>
            <div>
              <div style="font-size:0.82rem;font-weight:600;color:var(--text-primary)">Scorecard thresholds for releases</div>
              <div style="font-size:0.72rem;color:var(--text-secondary)">Turn the eval harness into a gate for future retrieval, model, and prompt changes.</div>
            </div>
          </div>
          <div class="overview-roadmap-item">
            <span class="overview-roadmap-impact">+0.2</span>
            <div>
              <div style="font-size:0.82rem;font-weight:600;color:var(--text-primary)">Expand German corporate corpus</div>
              <div style="font-size:0.72rem;color:var(--text-secondary)">Add more real PDFs so cross-company demo prompts have stronger coverage.</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ================================================================== -->
  <!-- S12: Known Limitations & Next Steps                                -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-limits">
    <div class="overview-section-title">
      <span class="overview-section-num">12</span> Known Limitations &amp; Next Steps
    </div>
    <div class="overview-two-col">
      <div class="card">
        <div class="card-header"><span class="card-title">Known Limitations</span></div>
        <ul style="font-size:0.8rem;color:var(--text-secondary);line-height:1.6;padding-left:1.2rem">
          <li><strong>BMW p04 retrieval gap:</strong> The BMW brand-list prompt is retrieval-side: the relevant list/table chunks do not reliably surface in top-k, so gemma4 answers honestly instead of inventing missing brands.</li>
          <li><strong>Cold starts:</strong> Warm gemma4 responses average about 7s in the eval set; first query after model expiry can still be slower.</li>
          <li><strong>Image relevance:</strong> Images only appear when their document has text hits. Use @filename + image keywords.</li>
          <li><strong>BMW text caveat:</strong> 486 noisy BMW text chunks are stored without embeddings and flagged in metadata. BMW image prompts are reliable; scoped BMW factual prompts still work.</li>
          <li><strong>RSS image quality:</strong> Some images have generic captions (logos, banners).</li>
          <li><strong>German-only output:</strong> Answers in German even when source is English (Siemens Annual Report).</li>
          <li><strong>No cross-session memory:</strong> Each chat is independent. No conversation persistence.</li>
        </ul>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">Planned Improvements</span></div>
        <ul style="font-size:0.8rem;color:var(--text-secondary);line-height:1.6;padding-left:1.2rem">
          <li><strong>BMW brand-list retrieval:</strong> Improve exact-list/table recall with lexical search, reranking, or targeted chunking around brand/holdings pages.</li>
          <li><strong>BMW cleanup:</strong> Suppress or repair embedding-error PDF text chunks if BMW text questions become broader demo-critical.</li>
          <li><strong>PDF click-to-source:</strong> Use stored bounding boxes to highlight cited regions in the original PDF.</li>
          <li><strong>Eval gates:</strong> Keep <code>scripts/eval_run.py</code> and scorecards as release checks for retrieval, prompt, and model changes.</li>
          <li><strong>Contextual re-captioning:</strong> Use surrounding text for better image descriptions.</li>
          <li><strong>Response optimization:</strong> Prompt compression, context trimming, and keep-alive/prewarm discipline.</li>
          <li><strong>More German PDFs:</strong> Expand the corporate document knowledge base.</li>
          <li><strong>Multi-language control:</strong> Answer in source language when appropriate.</li>
          <li><strong>Additional doc types:</strong> PowerPoint, Excel, structured data ingestion.</li>
        </ul>
      </div>
    </div>
  </div>

  <!-- ================================================================== -->
  <!-- S12: Discussion Points & Access Links                              -->
  <!-- ================================================================== -->
  <div class="overview-section" id="ov-discuss">
    <div class="overview-section-title">
      <span class="overview-section-num">13</span> Discussion Points &amp; Access
    </div>
    <div class="overview-two-col">
      <div class="card">
        <div class="card-header"><span class="card-title">Open Questions for Sven</span></div>
        <div>
          <div class="overview-question"><span class="overview-question-num">1.</span><span class="overview-question-text">Target audience for the real demo &mdash; technical or business stakeholders?</span></div>
          <div class="overview-question"><span class="overview-question-num">2.</span><span class="overview-question-text">Which corporate documents should we ingest for the production demo?</span></div>
          <div class="overview-question"><span class="overview-question-num">3.</span><span class="overview-question-text">Should we add more document types (PowerPoint, Excel)?</span></div>
          <div class="overview-question"><span class="overview-question-num">4.</span><span class="overview-question-text">Should the next sprint prioritize BMW list-retrieval quality or click-to-source PDF highlighting?</span></div>
          <div class="overview-question"><span class="overview-question-num">5.</span><span class="overview-question-text">Timeline for the real demo &mdash; how many weeks to prepare?</span></div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">Technical Access</span></div>
        <div class="overview-table-compact">
          <table>
            <thead><tr><th>Service</th><th>URL</th></tr></thead>
            <tbody>
              <tr><td>OpenWebUI</td><td><a href="https://spark-e010.tail907fce.ts.net:8451" target="_blank" rel="noopener">spark-e010:8451</a></td></tr>
              <tr><td>n8n</td><td><a href="https://spark-e010.tail907fce.ts.net:8450" target="_blank" rel="noopener">spark-e010:8450</a></td></tr>
              <tr><td>FileBrowser</td><td><a href="https://spark-e010.tail907fce.ts.net:8452" target="_blank" rel="noopener">spark-e010:8452</a></td></tr>
              <tr><td>Adminer</td><td><a href="https://spark-e010.tail907fce.ts.net:8453" target="_blank" rel="noopener">spark-e010:8453</a></td></tr>
              <tr><td>Assets Gallery</td><td><a href="https://spark-e010.tail907fce.ts.net:8454" target="_blank" rel="noopener">spark-e010:8454</a></td></tr>
              <tr><td>Control Center</td><td><a href="https://spark-e010.tail907fce.ts.net:8455" target="_blank" rel="noopener">spark-e010:8455</a></td></tr>
            </tbody>
          </table>
          <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.5rem">All URLs require Tailscale network access. Verify: <code>tailscale status</code></p>
        </div>
      </div>
    </div>
  </div>

  `; // end container.innerHTML

  // -----------------------------------------------------------------------
  // Section nav: smooth scroll + active state tracking
  // -----------------------------------------------------------------------
  const nav = document.getElementById('ov-nav');
  nav.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const target = document.getElementById(link.dataset.target);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  // Track active section on scroll
  const sectionEls = sections.map(s => document.getElementById(s.id)).filter(Boolean);
  const navLinks = nav.querySelectorAll('a');
  let scrollRaf = null;

  function updateActiveNav() {
    const scrollY = window.scrollY || document.documentElement.scrollTop;
    const navHeight = nav.offsetHeight + 16;
    let activeId = sections[0].id;
    for (const el of sectionEls) {
      if (el.offsetTop - navHeight <= scrollY) {
        activeId = el.id;
      }
    }
    navLinks.forEach(l => l.classList.toggle('active', l.dataset.target === activeId));
  }

  function onScroll() {
    if (scrollRaf) return;
    scrollRaf = requestAnimationFrame(() => {
      updateActiveNav();
      scrollRaf = null;
    });
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  updateActiveNav();

  // -----------------------------------------------------------------------
  // Copy-to-clipboard for prompt cards
  // -----------------------------------------------------------------------
  function _copyPrompt(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
      if (btn) {
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = orig, 1500);
      }
    }).catch(() => {
      Components.toast('Copy failed — try selecting manually', 'warning');
    });
  }

  container.querySelectorAll('.overview-prompt-text').forEach(el => {
    el.addEventListener('click', () => {
      const btn = el.parentElement.querySelector('.overview-copy-btn');
      _copyPrompt(el.textContent, btn);
    });
  });

  container.querySelectorAll('.overview-copy-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const card = btn.closest('.overview-prompt-card');
      const text = card ? card.querySelector('.overview-prompt-text').textContent : '';
      _copyPrompt(text, btn);
    });
  });

  // -----------------------------------------------------------------------
  // Cleanup
  // -----------------------------------------------------------------------
  return () => {
    window.removeEventListener('scroll', onScroll);
    if (scrollRaf) cancelAnimationFrame(scrollRaf);
  };
};

/* ===========================================================================
   HELPER FUNCTIONS (module-private)
   =========================================================================== */

function _renderArchSVG() {
  // Node positions
  const W = 120, H = 42, R = 6;

  const nodes = [
    // Top band: User Interfaces (y_center = 80)
    { id: 'openwebui',     label: 'OpenWebUI',      type: 'FE', port: ':8451', x: 96,  y: 80 },
    { id: 'filebrowser',   label: 'FileBrowser',     type: 'FE', port: ':8452', x: 248, y: 80 },
    { id: 'controlcenter', label: 'Control Center',  type: 'FE', port: ':8455', x: 400, y: 80 },
    { id: 'adminer',       label: 'Adminer',         type: 'FE', port: ':8453', x: 552, y: 80 },
    { id: 'assets',        label: 'Assets Gallery',  type: 'FE', port: ':8454', x: 704, y: 80 },

    // Middle band: Application Services (y_center = 240)
    { id: 'rag_gateway',   label: 'RAG Gateway',     type: 'SV', port: ':56155', x: 144, y: 240 },
    { id: 'n8n',           label: 'n8n',             type: 'WF', port: ':8450',  x: 336, y: 240 },
    { id: 'pdf_ingest',    label: 'PDF Ingest',      type: 'SV', port: ':8001',  x: 528, y: 240 },
    { id: 'rss_ingest',    label: 'RSS Ingest',      type: 'SV', port: ':8002',  x: 720, y: 240 },

    // Bottom band: Infrastructure (y_center = 400)
    { id: 'postgres',      label: 'PostgreSQL',      type: 'DB', port: ':56154', x: 336, y: 400 },
    { id: 'ollama',        label: 'Ollama (GPU)',     type: 'GPU', port: ':11434', x: 600, y: 400 },
  ];

  // Edges: [from, to, type] type = 'chat' | 'ingest' | 'internal'
  const edges = [
    // Chat flow (blue)
    ['openwebui',   'rag_gateway', 'chat'],
    ['rag_gateway', 'n8n',         'chat'],      // historical / n8n mode
    ['rag_gateway', 'postgres',    'chat'],       // direct context mode
    ['rag_gateway', 'ollama',      'chat'],       // LLM streaming

    // Ingestion flow (green)
    ['filebrowser', 'pdf_ingest',  'ingest'],
    ['pdf_ingest',  'ollama',      'ingest'],
    ['pdf_ingest',  'postgres',    'ingest'],
    ['rss_ingest',  'ollama',      'ingest'],
    ['rss_ingest',  'postgres',    'ingest'],

    // Internal (dashed gray)
    ['n8n',           'postgres',    'internal'],
    ['n8n',           'ollama',      'internal'],
    ['controlcenter', 'postgres',    'internal'],
    ['adminer',       'postgres',    'internal'],
  ];

  const nodeMap = {};
  nodes.forEach(n => nodeMap[n.id] = n);

  const typeColor = { FE: 'var(--text-secondary)', SV: '#5dade2', WF: 'var(--success)', DB: 'var(--warning)', GPU: 'var(--accent)' };

  let svg = `<svg viewBox="0 0 820 480" style="width:100%;height:auto;display:block" role="img" aria-label="MMRAG system architecture diagram showing 11 services in 3 layers: user interfaces, application services, and infrastructure">`;

  // Defs: arrowheads
  svg += `<defs>
    <marker id="arrow-chat" viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 3.5 L 0 7 z" fill="#5dade2"/>
    </marker>
    <marker id="arrow-ingest" viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 3.5 L 0 7 z" fill="var(--success)"/>
    </marker>
  </defs>`;

  // Band backgrounds
  svg += `<rect x="10" y="30" width="800" height="120" rx="8" fill="var(--bg-tertiary)" opacity="0.3"/>`;
  svg += `<rect x="10" y="190" width="800" height="100" rx="8" fill="var(--bg-tertiary)" opacity="0.2"/>`;
  svg += `<rect x="10" y="350" width="800" height="100" rx="8" fill="var(--bg-tertiary)" opacity="0.3"/>`;

  // Band labels (text already uppercased — SVG doesn't support text-transform)
  svg += `<text x="20" y="48" fill="var(--text-muted)" font-size="9" font-family="var(--font-mono)" letter-spacing="1px">USER INTERFACES</text>`;
  svg += `<text x="20" y="208" fill="var(--text-muted)" font-size="9" font-family="var(--font-mono)" letter-spacing="1px">APPLICATION SERVICES</text>`;
  svg += `<text x="20" y="368" fill="var(--text-muted)" font-size="9" font-family="var(--font-mono)" letter-spacing="1px">INFRASTRUCTURE</text>`;

  // Draw edges
  for (const [fromId, toId, type] of edges) {
    const f = nodeMap[fromId], t = nodeMap[toId];
    if (!f || !t) continue;

    // Calculate connection points
    let x1 = f.x, y1 = f.y + H/2;  // from bottom
    let x2 = t.x, y2 = t.y - H/2;  // to top

    // Same band: use sides
    if (Math.abs(f.y - t.y) < 50) {
      if (f.x < t.x) {
        x1 = f.x + W/2; y1 = f.y;
        x2 = t.x - W/2; y2 = t.y;
      } else {
        x1 = f.x - W/2; y1 = f.y;
        x2 = t.x + W/2; y2 = t.y;
      }
    }

    let stroke, dash, marker, width;
    if (type === 'chat') {
      stroke = '#5dade2'; dash = ''; marker = 'url(#arrow-chat)'; width = 2;
    } else if (type === 'ingest') {
      stroke = 'var(--success)'; dash = ''; marker = 'url(#arrow-ingest)'; width = 2;
    } else {
      stroke = 'var(--border)'; dash = '4,3'; marker = ''; width = 1.5;
    }

    // Curved path for cross-band connections
    if (Math.abs(f.y - t.y) > 50) {
      const midY = (y1 + y2) / 2;
      svg += `<path d="M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}" fill="none" stroke="${stroke}" stroke-width="${width}" ${dash ? `stroke-dasharray="${dash}"` : ''} ${marker ? `marker-end="${marker}"` : ''} opacity="0.7"/>`;
    } else {
      svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${width}" ${dash ? `stroke-dasharray="${dash}"` : ''} ${marker ? `marker-end="${marker}"` : ''} opacity="0.7"/>`;
    }
  }

  // Draw nodes
  for (const n of nodes) {
    const col = typeColor[n.type] || 'var(--text-secondary)';
    const x = n.x - W/2, y = n.y - H/2;

    // Node rect
    svg += `<rect x="${x}" y="${y}" width="${W}" height="${H}" rx="${R}" fill="var(--bg-secondary)" stroke="${col}" stroke-width="1.5"/>`;

    // Service name
    svg += `<text x="${n.x}" y="${n.y - 2}" text-anchor="middle" fill="var(--text-primary)" font-size="10" font-weight="600" font-family="var(--font-sans)">${n.label}</text>`;

    // Type badge + port
    svg += `<text x="${n.x}" y="${n.y + 12}" text-anchor="middle" fill="${col}" font-size="8" font-family="var(--font-mono)">${n.type} ${n.port}</text>`;
  }

  svg += `</svg>`;
  return svg;
}


function _feedRow(name, docs, chunks, maxChunks) {
  const pct = Math.round((chunks / maxChunks) * 100);
  const color = pct > 50 ? 'var(--accent)' : pct > 15 ? 'var(--warning)' : 'var(--success)';
  return `<tr>
    <td>${name}</td>
    <td style="text-align:right">${docs.toLocaleString()}</td>
    <td style="text-align:right">${chunks.toLocaleString()}</td>
    <td style="width:40%">
      <div class="overview-stat-bar"><div class="overview-stat-fill" style="width:${pct}%;background:${color}"></div></div>
    </td>
  </tr>`;
}


function _checkItem(title, desc) {
  return `<div class="overview-check-item">
    <span class="overview-check-icon">&#10003;</span>
    <div>
      <div class="overview-check-title">${title}</div>
      <div class="overview-check-desc">${desc}</div>
    </div>
  </div>`;
}


function _promptCard(num, text, tags, expected) {
  return `<div class="overview-prompt-card">
    <div class="overview-prompt-header">
      <span class="overview-prompt-num">P${num}</span>
      <button class="overview-copy-btn">Copy</button>
    </div>
    <div class="overview-prompt-text">${text}</div>
    <div class="overview-prompt-tags">
      ${tags.map(t => `<span class="badge badge-info">${t}</span>`).join('')}
    </div>
    <div class="overview-prompt-expected">${expected}</div>
  </div>`;
}


function _timelineItem(date, type, title, desc) {
  return `<div class="overview-timeline-item">
    <div class="overview-timeline-dot ${type}"></div>
    <div class="overview-timeline-date">${date}</div>
    <div class="overview-timeline-title">${title}</div>
    <div class="overview-timeline-desc">${desc}</div>
  </div>`;
}


function _scoreRow(label, score, weight) {
  const pct = Math.round(score * 10);
  const color = score >= 8 ? 'var(--success)' : score >= 6 ? 'var(--warning)' : 'var(--error)';
  return `<div class="overview-score-row">
    <span class="overview-score-label">${label} <span style="color:var(--text-muted);font-size:0.68rem">(${weight}%)</span></span>
    <div class="overview-score-bar"><div class="overview-score-fill" style="width:${pct}%;background:${color}"></div></div>
    <span class="overview-score-val" style="color:${color}">${score.toFixed(1)}</span>
  </div>`;
}
