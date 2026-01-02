// URL State Management for Vizzy
// Ensures all view state is reflected in URLs for shareability and back-button support

/**
 * URLState - Manages URL query parameters for application state
 * Provides methods to get, set, and sync state with the browser URL
 */
class URLState {
    /**
     * Get a single value from URL query parameters
     * @param {string} key - The parameter name to retrieve
     * @returns {string|null} - The value or null if not present
     */
    static get(key) {
        const params = new URLSearchParams(window.location.search);
        return params.get(key);
    }

    /**
     * Get all URL query parameters as an object
     * @returns {Object} - Key-value pairs of all query parameters
     */
    static getAll() {
        const params = new URLSearchParams(window.location.search);
        const result = {};
        for (const [key, value] of params) {
            result[key] = value;
        }
        return result;
    }

    /**
     * Set a single URL query parameter
     * Uses replaceState to avoid polluting browser history
     * @param {string} key - The parameter name
     * @param {string|null} value - The value to set, or null/empty to remove
     */
    static set(key, value) {
        const params = new URLSearchParams(window.location.search);
        if (value !== null && value !== undefined && value !== '') {
            params.set(key, value);
        } else {
            params.delete(key);
        }
        const newUrl = params.toString()
            ? `${window.location.pathname}?${params}`
            : window.location.pathname;
        history.replaceState(null, '', newUrl);
    }

    /**
     * Set multiple URL query parameters at once
     * @param {Object} updates - Key-value pairs to set/remove
     */
    static setMultiple(updates) {
        const params = new URLSearchParams(window.location.search);
        for (const [key, value] of Object.entries(updates)) {
            if (value !== null && value !== undefined && value !== '') {
                params.set(key, value);
            } else {
                params.delete(key);
            }
        }
        const newUrl = params.toString()
            ? `${window.location.pathname}?${params}`
            : window.location.pathname;
        history.replaceState(null, '', newUrl);
    }

    /**
     * Push state to history (creates a new history entry)
     * Use this when you want back button to restore previous state
     * @param {Object} updates - Key-value pairs to set/remove
     */
    static push(updates) {
        const params = new URLSearchParams(window.location.search);
        for (const [key, value] of Object.entries(updates)) {
            if (value !== null && value !== undefined && value !== '') {
                params.set(key, value);
            } else {
                params.delete(key);
            }
        }
        const newUrl = params.toString()
            ? `${window.location.pathname}?${params}`
            : window.location.pathname;
        history.pushState(null, '', newUrl);
    }

    /**
     * Remove all query parameters matching a pattern
     * @param {string} pattern - Substring to match in parameter names
     */
    static removeMatching(pattern) {
        const params = new URLSearchParams(window.location.search);
        const keysToDelete = [];
        for (const key of params.keys()) {
            if (key.includes(pattern)) {
                keysToDelete.push(key);
            }
        }
        keysToDelete.forEach(key => params.delete(key));
        const newUrl = params.toString()
            ? `${window.location.pathname}?${params}`
            : window.location.pathname;
        history.replaceState(null, '', newUrl);
    }

    /**
     * Clear all URL query parameters
     */
    static clear() {
        history.replaceState(null, '', window.location.pathname);
    }
}

/**
 * StateManager - Coordinates URL state with UI elements
 * Handles restoration on page load and syncs HTMX requests
 */
class StateManager {
    constructor() {
        this.initialized = false;
        this.stateHandlers = new Map();
    }

    /**
     * Register a handler for a specific state key
     * @param {string} key - The URL parameter key
     * @param {Object} handler - Object with restore(value) and optional selector
     */
    register(key, handler) {
        this.stateHandlers.set(key, handler);
    }

    /**
     * Initialize state management - restore from URL and set up listeners
     */
    init() {
        if (this.initialized) return;
        this.initialized = true;

        // Restore state from URL on page load
        this.restoreState();

        // Set up HTMX integration
        this.setupHtmxSync();

        // Handle browser back/forward buttons
        window.addEventListener('popstate', () => {
            this.restoreState();
        });
    }

    /**
     * Restore UI state from URL parameters
     */
    restoreState() {
        // Restore search query
        const query = URLState.get('q');
        if (query) {
            const searchInputs = document.querySelectorAll('[name="q"], [type="search"]');
            searchInputs.forEach(input => {
                input.value = query;
                // Trigger HTMX search if configured
                if (input.hasAttribute('hx-get') && typeof htmx !== 'undefined') {
                    htmx.trigger(input, 'keyup');
                }
            });
        }

        // Restore type filter
        const typeFilter = URLState.get('type');
        if (typeFilter) {
            const filterSelect = document.getElementById('type-filter');
            if (filterSelect) {
                filterSelect.value = typeFilter;
                // Trigger change event to apply filter
                filterSelect.dispatchEvent(new Event('change'));
            }
        }

        // Restore selected node highlight
        const nodeId = URLState.get('node');
        if (nodeId) {
            // Remove previous selection
            document.querySelectorAll('[data-node-id].selected').forEach(el => {
                el.classList.remove('selected');
            });
            // Add selection to matching node
            const nodeEl = document.querySelector(`[data-node-id="${nodeId}"]`);
            if (nodeEl) {
                nodeEl.classList.add('selected');
                nodeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }
        }

        // Restore sort order
        const sortBy = URLState.get('sort');
        if (sortBy) {
            const sortSelect = document.getElementById('sort-by');
            if (sortSelect) {
                sortSelect.value = sortBy;
                sortSelect.dispatchEvent(new Event('change'));
            }
        }

        // Restore depth filter
        const depth = URLState.get('depth');
        if (depth) {
            const depthInput = document.getElementById('depth-filter');
            if (depthInput) {
                depthInput.value = depth;
                depthInput.dispatchEvent(new Event('change'));
            }
        }

        // Run custom handlers
        for (const [key, handler] of this.stateHandlers) {
            const value = URLState.get(key);
            if (value && handler.restore) {
                handler.restore(value);
            }
        }
    }

    /**
     * Set up HTMX integration for URL state
     */
    setupHtmxSync() {
        // Include URL state in HTMX requests
        document.body.addEventListener('htmx:configRequest', (e) => {
            // Get relevant URL params to include in request
            const includeParams = ['type', 'sort', 'depth'];
            for (const param of includeParams) {
                const value = URLState.get(param);
                if (value && !e.detail.parameters[param]) {
                    e.detail.parameters[param] = value;
                }
            }
        });

        // Update URL after content swap if target specifies state
        document.body.addEventListener('htmx:afterSwap', (e) => {
            const target = e.detail.target;
            const stateData = target.dataset.urlState;
            if (stateData) {
                try {
                    const updates = JSON.parse(stateData);
                    URLState.setMultiple(updates);
                } catch (err) {
                    console.warn('URLState: Invalid data-url-state JSON', err);
                }
            }
        });

        // Handle HTMX-driven navigation (full page loads via hx-boost)
        document.body.addEventListener('htmx:beforeRequest', (e) => {
            // For boosted links, preserve certain state params
            if (e.detail.boosted) {
                const preserveParams = ['type', 'sort'];
                const currentParams = URLState.getAll();
                for (const param of preserveParams) {
                    if (currentParams[param] && !e.detail.path.includes(param + '=')) {
                        // Could add to path, but usually we want fresh state on navigation
                    }
                }
            }
        });
    }
}

// Global state manager instance
const stateManager = new StateManager();

/**
 * Bind common UI elements to URL state
 * Call this after DOM is ready
 */
function bindStateToUI() {
    // Bind search input
    const searchInputs = document.querySelectorAll('[name="q"], [type="search"]');
    searchInputs.forEach(input => {
        // Skip if already bound
        if (input._urlStateBound) return;
        input._urlStateBound = true;

        // Debounce URL update to avoid excessive history entries
        let debounceTimer;
        input.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                URLState.set('q', e.target.value);
            }, 500);
        });

        // Clear on blur if empty
        input.addEventListener('blur', (e) => {
            if (!e.target.value) {
                URLState.set('q', null);
            }
        });
    });

    // Bind type filter select
    const typeFilter = document.getElementById('type-filter');
    if (typeFilter && !typeFilter._urlStateBound) {
        typeFilter._urlStateBound = true;
        typeFilter.addEventListener('change', (e) => {
            URLState.set('type', e.target.value);
        });
    }

    // Bind sort select
    const sortSelect = document.getElementById('sort-by');
    if (sortSelect && !sortSelect._urlStateBound) {
        sortSelect._urlStateBound = true;
        sortSelect.addEventListener('change', (e) => {
            URLState.set('sort', e.target.value);
        });
    }

    // Bind depth filter
    const depthFilter = document.getElementById('depth-filter');
    if (depthFilter && !depthFilter._urlStateBound) {
        depthFilter._urlStateBound = true;
        depthFilter.addEventListener('change', (e) => {
            URLState.set('depth', e.target.value);
        });
    }

    // Bind node selection in lists
    document.querySelectorAll('.node-list a, [data-node-id]').forEach(link => {
        if (link._urlStateBound) return;
        link._urlStateBound = true;

        link.addEventListener('click', (e) => {
            const nodeId = link.dataset.nodeId;
            if (nodeId) {
                URLState.push({ node: nodeId });
            }
        });
    });
}

/**
 * Utility function to create a shareable URL with current state
 * @returns {string} - Full URL with current state parameters
 */
function getShareableURL() {
    return window.location.href;
}

/**
 * Copy current URL to clipboard
 * @returns {Promise<boolean>} - True if successful
 */
async function copyURLToClipboard() {
    try {
        await navigator.clipboard.writeText(getShareableURL());
        return true;
    } catch (err) {
        console.error('Failed to copy URL:', err);
        return false;
    }
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    stateManager.init();
    bindStateToUI();
});

// Re-bind after HTMX swaps (for dynamically added elements)
document.body.addEventListener('htmx:afterSwap', () => {
    bindStateToUI();
});

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.URLState = URLState;
    window.stateManager = stateManager;
    window.getShareableURL = getShareableURL;
    window.copyURLToClipboard = copyURLToClipboard;
}
