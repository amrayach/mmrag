/* ---------------------------------------------------------------------------
   app.js — Hash router, sidebar nav, keyboard shortcuts, init
   --------------------------------------------------------------------------- */

const App = {
  currentPage: null,
  currentCleanup: null,

  pages: {
    overview:      { render: Pages.overview,       title: 'System Overview' },
    dashboard:     { render: Pages.dashboard,      title: 'Dashboard' },
    services:      { render: Pages.services,       title: 'Services' },
    ingestion:     { render: Pages.ingestion,      title: 'Ingestion' },
    data_explorer: { render: Pages.data_explorer,  title: 'Data Explorer' },
    demo:          { render: Pages.demo,           title: 'Demo Mode' },
    rag:           { render: Pages.rag,            title: 'RAG Playground' },
    timeline:      { render: Pages.timeline,       title: 'Timeline' },
    docs:          { render: Pages.docs,           title: 'Docs' },
    system:        { render: Pages.system,         title: 'System' },
  },

  init() {
    window.addEventListener('hashchange', () => App.navigate());
    document.addEventListener('keydown', App.handleKey);

    // Sidebar toggle (responsive)
    const toggle = document.getElementById('sidebar-toggle');
    if (toggle) {
      toggle.addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('open');
      });
    }

    // Initial route
    if (!location.hash || location.hash === '#/') {
      location.hash = '#/dashboard';
    } else {
      App.navigate();
    }
  },

  navigate() {
    const hash = location.hash.replace('#/', '') || 'dashboard';
    const page = App.pages[hash];

    if (!page) {
      document.getElementById('page-container').innerHTML =
        '<div class="page-placeholder"><h2>Page not found</h2></div>';
      return;
    }

    // Cleanup previous page
    if (App.currentCleanup) {
      App.currentCleanup();
      App.currentCleanup = null;
    }

    App.currentPage = hash;

    // Update nav
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.page === hash);
    });

    // Close mobile sidebar
    document.getElementById('sidebar').classList.remove('open');

    // Render page
    const container = document.getElementById('page-container');
    const cleanup = page.render(container);
    if (typeof cleanup === 'function') {
      App.currentCleanup = cleanup;
    }

    // Update title
    document.title = `${page.title} | MMRAG Control Center`;
  },

  handleKey(e) {
    // Don't handle if typing in an input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

    // Key 0 for overview page
    if (e.key === '0' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      location.hash = '#/overview';
      e.preventDefault();
      return;
    }

    // Number keys 1-9 for page navigation (skip overview, which is key 0)
    const keyNum = parseInt(e.key);
    if (keyNum >= 1 && keyNum <= 9 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const pageNames = Object.keys(App.pages).filter(p => p !== 'overview');
      if (pageNames[keyNum - 1]) {
        location.hash = '#/' + pageNames[keyNum - 1];
        e.preventDefault();
      }
    }

    // R to refresh current page
    if (e.key === 'r' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      App.navigate();
      e.preventDefault();
    }
  },
};

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
