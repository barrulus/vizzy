// Vizzy client-side JavaScript

// Enable keyboard navigation
document.addEventListener('keydown', (e) => {
    // Focus search on '/'
    if (e.key === '/' && !e.target.matches('input, textarea')) {
        e.preventDefault();
        const search = document.querySelector('input[type="search"]');
        if (search) search.focus();
    }

    // Go back on Escape
    if (e.key === 'Escape') {
        const search = document.querySelector('input[type="search"]');
        if (document.activeElement === search) {
            search.blur();
        } else {
            history.back();
        }
    }
});

// Simple pan/zoom for graph containers
document.querySelectorAll('.graph-container').forEach(container => {
    let isPanning = false;
    let startX, startY, scrollLeft, scrollTop;

    container.addEventListener('mousedown', (e) => {
        // Only pan if not clicking a link
        if (e.target.closest('a')) return;

        isPanning = true;
        container.style.cursor = 'grabbing';
        startX = e.pageX - container.offsetLeft;
        startY = e.pageY - container.offsetTop;
        scrollLeft = container.scrollLeft;
        scrollTop = container.scrollTop;
    });

    container.addEventListener('mouseleave', () => {
        isPanning = false;
        container.style.cursor = 'grab';
    });

    container.addEventListener('mouseup', () => {
        isPanning = false;
        container.style.cursor = 'grab';
    });

    container.addEventListener('mousemove', (e) => {
        if (!isPanning) return;
        e.preventDefault();

        const x = e.pageX - container.offsetLeft;
        const y = e.pageY - container.offsetTop;
        const walkX = (x - startX) * 1.5;
        const walkY = (y - startY) * 1.5;

        container.scrollLeft = scrollLeft - walkX;
        container.scrollTop = scrollTop - walkY;
    });
});
