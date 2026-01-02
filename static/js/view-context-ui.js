/**
 * ViewContextUI - UI components for cross-view state visualization
 * Phase 8H-002: Cross-view state coordination
 *
 * Provides:
 * - Recent nodes panel
 * - Context indicator in navigation
 * - Filter state badges
 * - Navigation breadcrumb enhancement
 */

(function(window) {
    'use strict';

    const ViewContextUI = {
        _initialized: false,

        /**
         * Initialize UI components
         */
        init() {
            if (this._initialized) return;
            this._initialized = true;

            // Wait for CrossViewState to be ready
            if (window.CrossViewState) {
                CrossViewState.on('ready', () => this._setup());
                CrossViewState.on('contextChange', (ctx) => this._onContextChange(ctx));
            } else {
                // Fallback if CrossViewState not available
                document.addEventListener('DOMContentLoaded', () => this._setup());
            }
        },

        /**
         * Setup UI components
         */
        _setup() {
            this._createRecentNodesPanel();
            this._enhanceContextIndicator();
            this._enhanceFilterBadges();
            this._setupContextRestoration();
            this._setupNodeLinks();
        },

        /**
         * Create the recent nodes panel (appears in sidebar)
         */
        _createRecentNodesPanel() {
            // Find sidebar or create panel container
            const sidebar = document.querySelector('.lg\\:col-span-1 .space-y-4');
            if (!sidebar) return;

            // Check if we have CrossViewState
            if (!window.CrossViewState) return;

            const recentNodes = CrossViewState.getRecentNodes(5);
            if (recentNodes.length === 0) return;

            // Create the panel
            const panel = document.createElement('div');
            panel.id = 'recent-nodes-panel';
            panel.className = 'bg-white rounded-lg shadow p-4';
            panel.innerHTML = `
                <h3 class="font-semibold mb-3 flex items-center justify-between">
                    <span>Recent Nodes</span>
                    <button type="button"
                            onclick="ViewContextUI.clearRecentNodes()"
                            class="text-xs text-slate-400 hover:text-slate-600"
                            title="Clear history">
                        Clear
                    </button>
                </h3>
                <ul id="recent-nodes-list" class="space-y-1 text-sm">
                    ${this._renderRecentNodes(recentNodes)}
                </ul>
            `;

            // Insert at the top of sidebar
            sidebar.insertBefore(panel, sidebar.firstChild);
        },

        /**
         * Render recent nodes list items
         */
        _renderRecentNodes(nodes) {
            if (!nodes || nodes.length === 0) {
                return '<li class="text-slate-400 text-xs">No recent nodes</li>';
            }

            return nodes.map(node => {
                // Extract a readable title
                const title = this._extractNodeName(node.title);
                const timeAgo = this._formatTimeAgo(node.timestamp);

                return `
                    <li>
                        <a href="${node.url}"
                           class="flex items-center justify-between p-1 rounded hover:bg-slate-50 text-blue-600 hover:text-blue-800"
                           data-node-id="${node.nodeId}"
                           data-navigable>
                            <span class="truncate" title="${title}">${title}</span>
                            <span class="text-xs text-slate-400 ml-2 flex-shrink-0">${timeAgo}</span>
                        </a>
                    </li>
                `;
            }).join('');
        },

        /**
         * Extract node name from page title
         */
        _extractNodeName(title) {
            // Title format is usually "NodeName - Vizzy" or "NodeName - ImportName"
            if (!title) return 'Unknown';
            const parts = title.split(' - ');
            return parts[0] || title;
        },

        /**
         * Format timestamp as relative time
         */
        _formatTimeAgo(timestamp) {
            const seconds = Math.floor((Date.now() - timestamp) / 1000);

            if (seconds < 60) return 'just now';
            if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
            if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
            return `${Math.floor(seconds / 86400)}d ago`;
        },

        /**
         * Clear recent nodes history
         */
        clearRecentNodes() {
            if (window.CrossViewState) {
                CrossViewState.clear();
                const panel = document.getElementById('recent-nodes-panel');
                if (panel) {
                    panel.remove();
                }
            }
        },

        /**
         * Enhance the context indicator in navigation
         */
        _enhanceContextIndicator() {
            const contextDisplay = document.querySelector('.nav-context');
            if (!contextDisplay) return;

            if (!window.CrossViewState) return;

            const context = CrossViewState.getContext();

            // Add active filters indicator
            if (context.hasActiveFilters()) {
                const filtersIndicator = document.createElement('span');
                filtersIndicator.className = 'nav-context-filters';
                filtersIndicator.innerHTML = `
                    <span class="inline-flex items-center gap-1 ml-2 px-2 py-0.5 text-xs bg-blue-100 text-blue-700 rounded-full">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"/>
                        </svg>
                        Filters active
                    </span>
                `;
                contextDisplay.appendChild(filtersIndicator);
            }
        },

        /**
         * Enhance filter badges with cross-view awareness
         */
        _enhanceFilterBadges() {
            if (!window.CrossViewState) return;

            const context = CrossViewState.getContext();

            // Update type filter select
            const typeFilter = document.getElementById('type-filter');
            if (typeFilter && context.typeFilter) {
                typeFilter.value = context.typeFilter;

                // Add visual indicator if filter is active
                if (context.typeFilter !== 'all') {
                    typeFilter.classList.add('filter-active');
                }
            }

            // Update sort select
            const sortSelect = document.getElementById('sort-by');
            if (sortSelect && context.sortBy) {
                sortSelect.value = context.sortBy;
            }

            // Update depth filter
            const depthFilter = document.getElementById('depth-filter');
            if (depthFilter && context.depthFilter !== null) {
                depthFilter.value = context.depthFilter;
            }

            // Update search input
            const searchInputs = document.querySelectorAll('[name="q"], [type="search"]');
            searchInputs.forEach(input => {
                if (context.searchQuery && !input.value) {
                    input.value = context.searchQuery;
                }
            });
        },

        /**
         * Setup context restoration when navigating between views
         */
        _setupContextRestoration() {
            if (!window.CrossViewState) return;

            const context = CrossViewState.getContext();
            const viewType = CrossViewState.detectViewType();

            // Restore view-specific state
            switch (viewType) {
                case 'treemap':
                    this._restoreTreemapState(context);
                    break;
                case 'why_chain':
                    this._restoreWhyChainState(context);
                    break;
                case 'compare':
                    this._restoreCompareState(context);
                    break;
            }
        },

        /**
         * Restore treemap state
         */
        _restoreTreemapState(context) {
            const modeSelect = document.getElementById('treemap-mode');
            if (modeSelect && context.treemapMode) {
                modeSelect.value = context.treemapMode;
            }
        },

        /**
         * Restore why chain state
         */
        _restoreWhyChainState(context) {
            const maxDepthSelect = document.getElementById('max_depth');
            if (maxDepthSelect && context.whyChainMaxDepth) {
                maxDepthSelect.value = context.whyChainMaxDepth;
            }

            const maxGroupsSelect = document.getElementById('max_groups');
            if (maxGroupsSelect && context.whyChainMaxGroups) {
                maxGroupsSelect.value = context.whyChainMaxGroups;
            }

            const includeBuildDeps = document.querySelector('[name="include_build_deps"]');
            if (includeBuildDeps) {
                includeBuildDeps.checked = context.includeBuildDeps;
            }
        },

        /**
         * Restore compare state
         */
        _restoreCompareState(context) {
            const leftSelect = document.getElementById('left-import');
            if (leftSelect && context.compareLeftId) {
                leftSelect.value = context.compareLeftId;
            }

            const rightSelect = document.getElementById('right-import');
            if (rightSelect && context.compareRightId) {
                rightSelect.value = context.compareRightId;
            }
        },

        /**
         * Setup node links to use cross-view state
         */
        _setupNodeLinks() {
            if (!window.CrossViewState) return;

            // Enhance node links to record context
            document.querySelectorAll('[data-node-id]').forEach(link => {
                if (link._contextEnhanced) return;
                link._contextEnhanced = true;

                link.addEventListener('click', (e) => {
                    const nodeId = parseInt(link.dataset.nodeId, 10);
                    if (nodeId) {
                        CrossViewState.setNode(nodeId);
                    }
                });
            });

            // Re-run after HTMX swaps
            document.body.addEventListener('htmx:afterSwap', () => {
                this._setupNodeLinks();
            });
        },

        /**
         * Handle context changes
         */
        _onContextChange(context) {
            // Update filter visual states
            this._enhanceFilterBadges();

            // Emit custom event for other components
            document.dispatchEvent(new CustomEvent('vizzy:contextChange', {
                detail: context
            }));
        },

        /**
         * Create a context summary for display
         */
        getContextSummary() {
            if (!window.CrossViewState) return '';

            const context = CrossViewState.getContext();
            const parts = [];

            if (context.searchQuery) {
                parts.push(`Search: "${context.searchQuery}"`);
            }
            if (context.typeFilter !== 'all') {
                parts.push(`Type: ${context.typeFilter}`);
            }
            if (context.sortBy) {
                parts.push(`Sort: ${context.sortBy}`);
            }
            if (context.depthFilter !== null) {
                parts.push(`Depth: ${context.depthFilter}`);
            }

            return parts.join(' | ') || 'No active filters';
        },

        /**
         * Show context summary toast
         */
        showContextToast() {
            const summary = this.getContextSummary();

            const toast = document.createElement('div');
            toast.className = 'fixed bottom-4 right-4 bg-slate-800 text-white px-4 py-2 rounded-lg shadow-lg text-sm z-50 transition-opacity duration-300';
            toast.textContent = summary;
            document.body.appendChild(toast);

            setTimeout(() => {
                toast.style.opacity = '0';
                setTimeout(() => toast.remove(), 300);
            }, 2000);
        }
    };

    // Export to global scope
    window.ViewContextUI = ViewContextUI;

    // Initialize
    ViewContextUI.init();

})(window);
