(function () {
    var RENDER_BATCH_SIZE = 40;
    var activeAssets = [];
    var activeIndex = -1;

    function setLightboxMedia(asset, lightboxImg, lightboxVideo) {
        if (lightboxImg) {
            lightboxImg.src = '';
            lightboxImg.classList.add('d-none');
        }
        if (lightboxVideo) {
            lightboxVideo.pause();
            lightboxVideo.src = '';
            lightboxVideo.classList.add('d-none');
        }

        if (!asset) return;

        if (asset.media_type === 'video') {
            if (lightboxVideo) {
                lightboxVideo.src = asset.full_url || asset.preview_url || asset.thumb_url;
                lightboxVideo.classList.remove('d-none');
            }
            return;
        }

        if (lightboxImg) {
            lightboxImg.src = asset.preview_url || asset.thumb_url;
            lightboxImg.classList.remove('d-none');
        }
    }

    function initGallery(container) {
        if (!container || container.dataset.loaded === '1') return;

        var endpoint = container.dataset.galleryEndpoint;
        if (!endpoint) return;

        var statusEl = container.querySelector('.immich-gallery-status');
        var gridEl = container.querySelector('.immich-gallery-grid');
        var lightboxEl = document.getElementById('immichLightbox');
        var lightboxImg = document.getElementById('immichLightboxImage');
        var lightboxVideo = document.getElementById('immichLightboxVideo');

        if (!gridEl) return;

        function setStatus(message) {
            if (statusEl) {
                statusEl.textContent = message;
            }
        }

        function openLightbox(assets, index) {
            activeAssets = assets || [];
            activeIndex = index;
            setLightboxMedia(activeAssets[activeIndex], lightboxImg, lightboxVideo);

            if (window.bootstrap && window.bootstrap.Modal && lightboxEl) {
                var modalApi = window.bootstrap.Modal;
                if (typeof modalApi.getOrCreateInstance === 'function') {
                    modalApi.getOrCreateInstance(lightboxEl).show();
                } else {
                    new modalApi(lightboxEl).show();
                }
            }
        }

        function createAssetItem(asset, index, assets) {
            var item = document.createElement('button');
            item.type = 'button';
            item.className = 'immich-gallery-item' + (asset.media_type === 'video' ? ' is-video' : '');

            var thumb = document.createElement('img');
            thumb.loading = 'lazy';
            thumb.src = asset.thumb_url;
            thumb.alt = asset.media_type === 'video' ? 'Trip video' : 'Trip photo';
            item.appendChild(thumb);

            if (asset.media_type === 'video') {
                var badge = document.createElement('span');
                badge.className = 'immich-gallery-video-badge';
                badge.innerHTML = '<span class="ui-icon">▶</span>';
                item.appendChild(badge);
            }

            item.addEventListener('click', function () {
                openLightbox(assets, index);
            });

            return item;
        }

        function renderAssets(assets) {
            gridEl.innerHTML = '';
            if (!assets.length) {
                setStatus('No photos found in this album.');
                return;
            }

            var index = 0;
            function renderChunk() {
                var end = Math.min(index + RENDER_BATCH_SIZE, assets.length);
                var fragment = document.createDocumentFragment();

                for (; index < end; index += 1) {
                    fragment.appendChild(createAssetItem(assets[index], index, assets));
                }

                gridEl.appendChild(fragment);

                if (index < assets.length) {
                    setStatus('Loading media ' + index + '/' + assets.length + '...');
                    window.requestAnimationFrame(renderChunk);
                } else {
                    setStatus('Loaded ' + assets.length + ' items.');
                }
            }

            setStatus('Preparing gallery...');
            window.requestAnimationFrame(renderChunk);
        }

        setStatus('Loading gallery...');
        fetch(endpoint)
            .then(function (res) {
                if (!res.ok) throw new Error('Failed to load gallery');
                return res.json();
            })
            .then(function (payload) {
                renderAssets(payload.assets || []);
                container.dataset.loaded = '1';
            })
            .catch(function () {
                setStatus('Gallery is currently unavailable.');
            });
    }

    function observeAndLoad(container) {
        if (!('IntersectionObserver' in window)) {
            initGallery(container);
            return;
        }

        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    initGallery(container);
                    observer.disconnect();
                }
            });
        }, { rootMargin: '200px 0px' });

        observer.observe(container);
    }

    document.addEventListener('DOMContentLoaded', function () {
        var galleries = document.querySelectorAll('.immich-gallery');
        galleries.forEach(observeAndLoad);

        var lightboxEl = document.getElementById('immichLightbox');
        var lightboxVideo = document.getElementById('immichLightboxVideo');
        var lightboxImg = document.getElementById('immichLightboxImage');
        var prevBtn = document.getElementById('immichLightboxPrev');
        var nextBtn = document.getElementById('immichLightboxNext');

        function navigate(delta) {
            if (!activeAssets.length) return;
            activeIndex = (activeIndex + delta + activeAssets.length) % activeAssets.length;
            setLightboxMedia(activeAssets[activeIndex], lightboxImg, lightboxVideo);
        }

        if (prevBtn) {
            prevBtn.addEventListener('click', function () {
                navigate(-1);
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', function () {
                navigate(1);
            });
        }

        if (lightboxEl && lightboxVideo) {
            lightboxEl.addEventListener('shown.bs.modal', function () {
                document.body.classList.add('immich-lightbox-open');
            });

            lightboxEl.addEventListener('hidden.bs.modal', function () {
                lightboxVideo.pause();
                lightboxVideo.src = '';
                activeAssets = [];
                activeIndex = -1;
                document.body.classList.remove('immich-lightbox-open');
            });
        }

        document.addEventListener('keydown', function (event) {
            if (!lightboxEl || !lightboxEl.classList.contains('show')) return;
            if (event.key === 'ArrowLeft') {
                navigate(-1);
            } else if (event.key === 'ArrowRight') {
                navigate(1);
            }
        });

        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('[data-immich-gallery-target]');
            if (!trigger) return;
            var target = document.querySelector(trigger.getAttribute('data-immich-gallery-target'));
            initGallery(target);
        });

        document.querySelectorAll('.modal').forEach(function (modalEl) {
            modalEl.addEventListener('shown.bs.modal', function () {
                var targetGallery = modalEl.querySelector('.immich-gallery');
                initGallery(targetGallery);
            });
        });
    });
})();

