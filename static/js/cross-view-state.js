/**
 * CrossViewState - Coordinates state between different views in Vizzy
 * Phase 8H-002: Cross-view state coordination
 *
 * This module provides:
 * - Persistent view context (selected node, filters, search query)
 * - State synchronization between views
 * - Navigation history with context preservation
 * - Event-driven state updates
 */

(function(window) {
    'use strict';

    // Storage key prefix for localStorage
    const STORAGE_PREFIX = 'vizzy_';

    // Session storage key for cross-view context
    const CONTEXT_KEY = STORAGE_PREFIX + 'view_context';

    // Navigation history key
    const HISTORY_KEY = STORAGE_PREFIX + 'nav_history';

    // Maximum history entries to keep
    const MAX_HISTORY = 50;

    /**
     * ViewContext - Represents the current state that should persist across views
     */
    class ViewContext {
        constructor(data = {}) {
            // Core identifiers
            this.importId = data.importId || null;
            this.nodeId = data.nodeId || null;

            // Search state
            this.searchQuery = data.searchQuery || '';

            // Filter states
            this.typeFilter = data.typeFilter || 'all';
            this.sortBy = data.sortBy || '';
            this.depthFilter = data.depthFilter || null;
            this.dependencyType = data.dependencyType || 'all'; // all, runtime, build

            // View-specific states
            this.treemapMode = data.treemapMode || 'application';
            this.treemapZoomStack = data.treemapZoomStack || [];
            this.whyChainMaxDepth = data.whyChainMaxDepth || 10;
            this.whyChainMaxGroups = data.whyChainMaxGroups || 10;
            this.includeBuildDeps = data.includeBuildDeps !== undefined ? data.includeBuildDeps : false;

            // Comparison state
            this.compareLeftId = data.compareLeftId || null;
            this.compareRightId = data.compareRightId || null;

            // UI state
            this.sidebarCollapsed = data.sidebarCollapsed || false;
            this.expandedGroups = data.expandedGroups || [];

            // Timestamp for cache invalidation
            this.timestamp = data.timestamp || Date.now();
        }

        /**
         * Create a copy with updated values
         */
        with(updates) {
            return new ViewContext({
                ...this.toJSON(),
                ...updates,
                timestamp: Date.now()
            });
        }

        /**
         * Serialize to JSON for storage
         */
        toJSON() {
            return {
                importId: this.importId,
                nodeId: this.nodeId,
                searchQuery: this.searchQuery,
                typeFilter: this.typeFilter,
                sortBy: this.sortBy,
                depthFilter: this.depthFilter,
                dependencyType: this.dependencyType,
                treemapMode: this.treemapMode,
                treemapZoomStack: this.treemapZoomStack,
                whyChainMaxDepth: this.whyChainMaxDepth,
                whyChainMaxGroups: this.whyChainMaxGroups,
                includeBuildDeps: this.includeBuildDeps,
                compareLeftId: this.compareLeftId,
                compareRightId: this.compareRightId,
                sidebarCollapsed: this.sidebarCollapsed,
                expandedGroups: this.expandedGroups,
                timestamp: this.timestamp
            };
        }

        /**
         * Check if context has a specific import selected
         */
        hasImport() {
            return this.importId !== null;
        }

        /**
         * Check if context has a specific node selected
         */
        hasNode() {
            return this.nodeId !== null;
        }

        /**
         * Check if any filters are active
         */
        hasActiveFilters() {
            return this.typeFilter !== 'all' ||
                   this.sortBy !== '' ||
                   this.depthFilter !== null ||
                   this.dependencyType !== 'all';
        }
    }

    /**
     * NavigationEntry - Represents a single entry in navigation history
     */
    class NavigationEntry {
        constructor(data = {}) {
            this.url = data.url || window.location.href;
            this.title = data.title || document.title;
            this.viewType = data.viewType || CrossViewState.detectViewType();
            this.context = data.context ? new ViewContext(data.context) : new ViewContext();
            this.timestamp = data.timestamp || Date.now();
        }

        toJSON() {
            return {
                url: this.url,
                title: this.title,
                viewType: this.viewType,
                context: this.context.toJSON(),
                timestamp: this.timestamp
            };
        }
    }

    /**
     * CrossViewState - Main coordinator for view state
     */
    const CrossViewState = {
        _context: null,
        _history: [],
        _listeners: new Map(),
        _initialized: false,

        /**
         * Initialize the cross-view state system
         */
        init() {
            if (this._initialized) return;
            this._initialized = true;

            // Load context from storage
            this._context = this._loadContext();
            this._history = this._loadHistory();

            // Sync with URL state if available
            this._syncWithURLState();

            // Listen for storage events from other tabs
            window.addEventListener('storage', (e) => {
                if (e.key === CONTEXT_KEY) {
                    this._context = this._loadContext();
                    this._emit('contextChange', this._context);
                }
            });

            // Listen for popstate for back/forward navigation
            window.addEventListener('popstate', () => {
                this._syncWithURLState();
                this._emit('navigate', this._context);
            });

            // Record current page in history
            this._recordNavigation();

            // Set up beforeunload to save state
            window.addEventListener('beforeunload', () => {
                this._saveContext();
                this._saveHistory();
            });

            // Emit initial ready event
            this._emit('ready', this._context);
        },

        /**
         * Get the current view context
         */
        getContext() {
            return this._context || new ViewContext();
        },

        /**
         * Update the view context with new values
         */
        updateContext(updates) {
            this._context = this._context.with(updates);
            this._saveContext();
            this._updateURLState(updates);
            this._emit('contextChange', this._context);
            return this._context;
        },

        /**
         * Set the current import ID and optionally clear node selection
         */
        setImport(importId, clearNode = true) {
            const updates = { importId };
            if (clearNode) {
                updates.nodeId = null;
            }
            return this.updateContext(updates);
        },

        /**
         * Set the currently selected node
         */
        setNode(nodeId, importId = null) {
            const updates = { nodeId };
            if (importId !== null) {
                updates.importId = importId;
            }
            return this.updateContext(updates);
        },

        /**
         * Set the search query
         */
        setSearch(query) {
            return this.updateContext({ searchQuery: query });
        },

        /**
         * Set a filter value
         */
        setFilter(filterName, value) {
            const updates = {};
            updates[filterName] = value;
            return this.updateContext(updates);
        },

        /**
         * Clear all filters
         */
        clearFilters() {
            return this.updateContext({
                typeFilter: 'all',
                sortBy: '',
                depthFilter: null,
                dependencyType: 'all'
            });
        },

        /**
         * Set comparison imports
         */
        setComparison(leftId, rightId) {
            return this.updateContext({
                compareLeftId: leftId,
                compareRightId: rightId
            });
        },

        /**
         * Get navigation history
         */
        getHistory() {
            return [...this._history];
        },

        /**
         * Get recent nodes from history (unique, most recent first)
         */
        getRecentNodes(limit = 10) {
            const seen = new Set();
            const recentNodes = [];

            for (const entry of this._history) {
                if (entry.context.nodeId && !seen.has(entry.context.nodeId)) {
                    seen.add(entry.context.nodeId);
                    recentNodes.push({
                        nodeId: entry.context.nodeId,
                        importId: entry.context.importId,
                        title: entry.title,
                        url: entry.url,
                        timestamp: entry.timestamp
                    });
                    if (recentNodes.length >= limit) break;
                }
            }

            return recentNodes;
        },

        /**
         * Get recent imports from history (unique, most recent first)
         */
        getRecentImports(limit = 10) {
            const seen = new Set();
            const recentImports = [];

            for (const entry of this._history) {
                if (entry.context.importId && !seen.has(entry.context.importId)) {
                    seen.add(entry.context.importId);
                    recentImports.push({
                        importId: entry.context.importId,
                        title: entry.title,
                        url: entry.url,
                        viewType: entry.viewType,
                        timestamp: entry.timestamp
                    });
                    if (recentImports.length >= limit) break;
                }
            }

            return recentImports;
        },

        /**
         * Navigate to a view while preserving context
         */
        navigateTo(url, contextOverrides = {}) {
            // Update context with overrides
            if (Object.keys(contextOverrides).length > 0) {
                this.updateContext(contextOverrides);
            }

            // Add to history
            this._recordNavigation();

            // Navigate
            window.location.href = url;
        },

        /**
         * Navigate to a node detail view
         */
        navigateToNode(nodeId, importId = null) {
            importId = importId || this._context.importId;
            this.setNode(nodeId, importId);
            this.navigateTo(`/graph/node/${nodeId}`);
        },

        /**
         * Navigate to explore view for an import
         */
        navigateToExplore(importId = null) {
            importId = importId || this._context.importId;
            if (importId) {
                this.setImport(importId);
                this.navigateTo(`/explore/${importId}`);
            }
        },

        /**
         * Navigate to why chain view for a node
         */
        navigateToWhyChain(nodeId, importId = null) {
            importId = importId || this._context.importId;
            this.setNode(nodeId, importId);
            this.navigateTo(`/analyze/why/${importId}/${nodeId}`);
        },

        /**
         * Navigate to dashboard for an import
         */
        navigateToDashboard(importId = null) {
            importId = importId || this._context.importId;
            if (importId) {
                this.setImport(importId);
                this.navigateTo(`/dashboard/${importId}`);
            }
        },

        /**
         * Navigate to treemap for an import
         */
        navigateToTreemap(importId = null) {
            importId = importId || this._context.importId;
            if (importId) {
                this.setImport(importId);
                this.navigateTo(`/treemap/${importId}`);
            }
        },

        /**
         * Generate a shareable URL with current context
         */
        getShareableURL() {
            const url = new URL(window.location.href);
            const context = this.getContext();

            // Add relevant context to URL params
            if (context.searchQuery) {
                url.searchParams.set('q', context.searchQuery);
            }
            if (context.typeFilter !== 'all') {
                url.searchParams.set('type', context.typeFilter);
            }
            if (context.sortBy) {
                url.searchParams.set('sort', context.sortBy);
            }
            if (context.depthFilter !== null) {
                url.searchParams.set('depth', context.depthFilter.toString());
            }
            if (context.nodeId) {
                url.searchParams.set('node', context.nodeId.toString());
            }

            return url.toString();
        },

        /**
         * Copy shareable URL to clipboard
         */
        async copyShareableURL() {
            const url = this.getShareableURL();
            try {
                await navigator.clipboard.writeText(url);
                this._emit('urlCopied', url);
                return true;
            } catch (err) {
                console.error('Failed to copy URL:', err);
                return false;
            }
        },

        /**
         * Register an event listener
         */
        on(event, callback) {
            if (!this._listeners.has(event)) {
                this._listeners.set(event, new Set());
            }
            this._listeners.get(event).add(callback);
            return () => this.off(event, callback);
        },

        /**
         * Remove an event listener
         */
        off(event, callback) {
            if (this._listeners.has(event)) {
                this._listeners.get(event).delete(callback);
            }
        },

        /**
         * Emit an event
         */
        _emit(event, data) {
            if (this._listeners.has(event)) {
                for (const callback of this._listeners.get(event)) {
                    try {
                        callback(data);
                    } catch (err) {
                        console.error(`Error in ${event} listener:`, err);
                    }
                }
            }
        },

        /**
         * Detect the current view type from URL
         */
        detectViewType() {
            const path = window.location.pathname;

            if (path === '/' || path === '/index') return 'home';
            if (path.startsWith('/explore/')) return 'explore';
            if (path.startsWith('/dashboard/')) return 'dashboard';
            if (path.startsWith('/treemap/')) return 'treemap';
            if (path.startsWith('/graph/node/')) return 'node';
            if (path.startsWith('/graph/cluster/')) return 'cluster';
            if (path.startsWith('/analyze/duplicates/')) return 'duplicates';
            if (path.startsWith('/analyze/path/')) return 'path';
            if (path.startsWith('/analyze/loops/')) return 'loops';
            if (path.startsWith('/analyze/redundant/')) return 'redundant';
            if (path.startsWith('/analyze/why/')) return 'why_chain';
            if (path.startsWith('/analyze/sankey/')) return 'sankey';
            if (path.startsWith('/analyze/matrix/')) return 'matrix';
            if (path.startsWith('/compare')) return 'compare';
            if (path.startsWith('/baselines')) return 'baselines';
            if (path.startsWith('/defined/')) return 'defined';
            if (path.startsWith('/module-packages/')) return 'module_packages';
            if (path.startsWith('/visual/')) return 'visual';
            if (path.startsWith('/impact/')) return 'impact';

            return 'unknown';
        },

        /**
         * Extract context from current URL
         */
        _extractContextFromURL() {
            const path = window.location.pathname;
            const params = new URLSearchParams(window.location.search);
            const updates = {};

            // Extract import ID from path
            const importMatch = path.match(/\/(explore|dashboard|treemap|analyze\/\w+|graph\/cluster|defined|module-packages)\/(\d+)/);
            if (importMatch) {
                updates.importId = parseInt(importMatch[2], 10);
            }

            // Extract node ID from path
            const nodeMatch = path.match(/\/graph\/node\/(\d+)/);
            if (nodeMatch) {
                updates.nodeId = parseInt(nodeMatch[1], 10);
            }

            // Extract why chain node ID
            const whyMatch = path.match(/\/analyze\/why\/(\d+)\/(\d+)/);
            if (whyMatch) {
                updates.importId = parseInt(whyMatch[1], 10);
                updates.nodeId = parseInt(whyMatch[2], 10);
            }

            // Extract query params
            if (params.has('q')) {
                updates.searchQuery = params.get('q');
            }
            if (params.has('type')) {
                updates.typeFilter = params.get('type');
            }
            if (params.has('sort')) {
                updates.sortBy = params.get('sort');
            }
            if (params.has('depth')) {
                updates.depthFilter = parseInt(params.get('depth'), 10);
            }
            if (params.has('node')) {
                updates.nodeId = parseInt(params.get('node'), 10);
            }
            if (params.has('left')) {
                updates.compareLeftId = parseInt(params.get('left'), 10);
            }
            if (params.has('right')) {
                updates.compareRightId = parseInt(params.get('right'), 10);
            }
            if (params.has('max_depth')) {
                updates.whyChainMaxDepth = parseInt(params.get('max_depth'), 10);
            }
            if (params.has('max_groups')) {
                updates.whyChainMaxGroups = parseInt(params.get('max_groups'), 10);
            }
            if (params.has('include_build_deps')) {
                updates.includeBuildDeps = params.get('include_build_deps') === 'true';
            }

            return updates;
        },

        /**
         * Sync context with current URL state
         */
        _syncWithURLState() {
            const urlContext = this._extractContextFromURL();
            if (Object.keys(urlContext).length > 0) {
                this._context = this._context.with(urlContext);
                this._saveContext();
            }
        },

        /**
         * Update URL state based on context changes
         */
        _updateURLState(updates) {
            // Only update URL for certain fields
            const urlParams = ['searchQuery', 'typeFilter', 'sortBy', 'depthFilter', 'nodeId'];
            const relevantUpdates = Object.keys(updates).filter(k => urlParams.includes(k));

            if (relevantUpdates.length === 0) return;

            const params = new URLSearchParams(window.location.search);

            if (updates.searchQuery !== undefined) {
                if (updates.searchQuery) {
                    params.set('q', updates.searchQuery);
                } else {
                    params.delete('q');
                }
            }
            if (updates.typeFilter !== undefined) {
                if (updates.typeFilter !== 'all') {
                    params.set('type', updates.typeFilter);
                } else {
                    params.delete('type');
                }
            }
            if (updates.sortBy !== undefined) {
                if (updates.sortBy) {
                    params.set('sort', updates.sortBy);
                } else {
                    params.delete('sort');
                }
            }
            if (updates.depthFilter !== undefined) {
                if (updates.depthFilter !== null) {
                    params.set('depth', updates.depthFilter.toString());
                } else {
                    params.delete('depth');
                }
            }
            if (updates.nodeId !== undefined) {
                if (updates.nodeId !== null) {
                    params.set('node', updates.nodeId.toString());
                } else {
                    params.delete('node');
                }
            }

            const newUrl = params.toString()
                ? `${window.location.pathname}?${params}`
                : window.location.pathname;

            history.replaceState(null, '', newUrl);
        },

        /**
         * Load context from storage
         */
        _loadContext() {
            try {
                const stored = sessionStorage.getItem(CONTEXT_KEY);
                if (stored) {
                    return new ViewContext(JSON.parse(stored));
                }
            } catch (err) {
                console.warn('Failed to load view context:', err);
            }
            return new ViewContext();
        },

        /**
         * Save context to storage
         */
        _saveContext() {
            try {
                sessionStorage.setItem(CONTEXT_KEY, JSON.stringify(this._context.toJSON()));
            } catch (err) {
                console.warn('Failed to save view context:', err);
            }
        },

        /**
         * Load navigation history from storage
         */
        _loadHistory() {
            try {
                const stored = localStorage.getItem(HISTORY_KEY);
                if (stored) {
                    return JSON.parse(stored).map(e => new NavigationEntry(e));
                }
            } catch (err) {
                console.warn('Failed to load navigation history:', err);
            }
            return [];
        },

        /**
         * Save navigation history to storage
         */
        _saveHistory() {
            try {
                // Keep only recent history
                const toSave = this._history.slice(0, MAX_HISTORY);
                localStorage.setItem(HISTORY_KEY, JSON.stringify(toSave.map(e => e.toJSON())));
            } catch (err) {
                console.warn('Failed to save navigation history:', err);
            }
        },

        /**
         * Record current page in navigation history
         */
        _recordNavigation() {
            const entry = new NavigationEntry({
                url: window.location.href,
                title: document.title,
                viewType: this.detectViewType(),
                context: this._context
            });

            // Avoid duplicate consecutive entries
            if (this._history.length > 0 && this._history[0].url === entry.url) {
                // Update existing entry
                this._history[0] = entry;
            } else {
                // Add new entry
                this._history.unshift(entry);
            }

            // Trim history
            if (this._history.length > MAX_HISTORY) {
                this._history = this._history.slice(0, MAX_HISTORY);
            }

            this._saveHistory();
        },

        /**
         * Clear all stored state (for debugging/reset)
         */
        clear() {
            this._context = new ViewContext();
            this._history = [];
            sessionStorage.removeItem(CONTEXT_KEY);
            localStorage.removeItem(HISTORY_KEY);
            this._emit('cleared');
        }
    };

    // Export to global scope
    window.CrossViewState = CrossViewState;
    window.ViewContext = ViewContext;

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => CrossViewState.init());
    } else {
        CrossViewState.init();
    }

})(window);
