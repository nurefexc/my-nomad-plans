document.addEventListener('DOMContentLoaded', function() {
    function initCarousel(id) {
        const carouselEl = document.getElementById(id);
        if (!carouselEl) return;

        const carousel = bootstrap.Carousel.getOrCreateInstance(carouselEl);

        // Jump to current logic
        const jumpBtn = carouselEl.querySelector('.jump-to-current-btn');
        if (jumpBtn) {
            jumpBtn.addEventListener('click', function() {
                // In our list, the ongoing adventure is always the first item (index 0)
                // because we sort highlight_trips to have active trips first.
                // However, we can also search for the item with the 'Ongoing Adventure' badge
                // or just default to 0.
                carousel.to(0);
            });
        }

        // Update indicators on slide (if any exist)
        carouselEl.addEventListener('slide.bs.carousel', function(e) {
            const indicators = carouselEl.querySelectorAll('.carousel-indicators-top .indicator-dot');
            if (indicators.length > 0) {
                indicators.forEach((dot, idx) => {
                    if (idx === e.to) {
                        dot.classList.add('active');
                    } else {
                        dot.classList.remove('active');
                    }
                });
            }
        });

        // Touch swipe support
        let touchStartX = 0;
        let touchEndX = 0;

        carouselEl.addEventListener('touchstart', e => {
            touchStartX = e.changedTouches[0].screenX;
        }, {passive: true});

        carouselEl.addEventListener('touchend', e => {
            touchEndX = e.changedTouches[0].screenX;
            handleSwipe();
        }, {passive: true});

        function handleSwipe() {
            if (touchEndX < touchStartX - 50) carousel.next();
            if (touchEndX > touchStartX + 50) carousel.prev();
        }

        // Global weather update support for shared trips
        carouselEl.addEventListener('weatherUpdated', function(e) {
            const { tripId, weather } = e.detail;
            const content = carouselEl.querySelector(`.weather-content[data-trip-id="${tripId}"]`);
            if (content) {
                content.innerText = `${weather.temperature}°C, ${weather.description}`;
            }
        });
    }

    initCarousel('adventureCarousel');
    initCarousel('sharedAdventureCarousel');
});
