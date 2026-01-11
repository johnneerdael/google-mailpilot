// Secretary Web UI - Alpine.js extensions and utilities

document.addEventListener('alpine:init', () => {
    // Email collapse animation
    Alpine.directive('collapse', (el, { expression }, { effect, cleanup }) => {
        const height = el.scrollHeight;
        
        effect(() => {
            if (el._x_isShown === false) {
                el.style.height = '0px';
                el.style.overflow = 'hidden';
            } else {
                el.style.height = height + 'px';
                el.style.overflow = 'visible';
            }
        });
    });
});

function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

function shouldAttachCsrf(url, method) {
    const m = (method || 'GET').toUpperCase();
    if (m === 'GET' || m === 'HEAD' || m === 'OPTIONS') return false;
    try {
        const u = url ? new URL(url, window.location.href) : null;
        if (u && u.origin !== window.location.origin) return false;
    } catch {
        return false;
    }
    return true;
}

// HTMX configuration
document.body.addEventListener('htmx:configRequest', (event) => {
    const verb = (event.detail.verb || 'GET').toUpperCase();
    if (verb !== 'GET') {
        const csrf = getCsrfToken();
        if (csrf) event.detail.headers['X-CSRF-Token'] = csrf;
    }

    document.body.classList.add('htmx-request');
});

const _fetch = window.fetch.bind(window);
window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : input?.url;
    const method = init?.method || (typeof input !== 'string' ? input?.method : 'GET');
    if (shouldAttachCsrf(url, method)) {
        const csrf = getCsrfToken();
        const headers = new Headers(init?.headers || (typeof input !== 'string' ? input?.headers : undefined) || {});
        if (csrf && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrf);
        init = { ...(init || {}), headers };
    }
    return _fetch(input, init);
};

document.body.addEventListener('htmx:afterRequest', (event) => {
    document.body.classList.remove('htmx-request');
});
