(function () {
    function qs(sel, root) {
        return (root || document).querySelector(sel);
    }

    function qsa(sel, root) {
        return Array.from((root || document).querySelectorAll(sel));
    }

    function createBackdrop() {
        var existing = qs('.modal-backdrop');
        if (existing) return existing;
        var backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop';
        document.body.appendChild(backdrop);
        return backdrop;
    }

    function removeBackdrop() {
        var backdrop = qs('.modal-backdrop');
        if (backdrop) backdrop.remove();
    }

    class Modal {
        constructor(element) {
            this.element = element;
        }

        static getOrCreateInstance(element) {
            if (!element) return new Modal(null);
            if (!element.__nomadModalInstance) {
                element.__nomadModalInstance = new Modal(element);
            }
            return element.__nomadModalInstance;
        }

        show() {
            if (!this.element) return;
            this.element.classList.add('show');
            this.element.style.display = 'block';
            this.element.removeAttribute('aria-hidden');
            this.element.dispatchEvent(new CustomEvent('show.bs.modal'));
            document.body.classList.add('modal-open');
            createBackdrop();
            this.element.dispatchEvent(new CustomEvent('shown.bs.modal'));
        }

        hide() {
            if (!this.element) return;
            this.element.dispatchEvent(new CustomEvent('hide.bs.modal'));
            this.element.classList.remove('show');
            this.element.style.display = 'none';
            this.element.setAttribute('aria-hidden', 'true');
            document.body.classList.remove('modal-open');
            removeBackdrop();
            this.element.dispatchEvent(new CustomEvent('hidden.bs.modal'));
        }
    }

    class Toast {
        constructor(element, options) {
            this.element = element;
            this.delay = (options && options.delay) || 3000;
            this.timeoutId = null;
        }

        show() {
            if (!this.element) return;
            this.element.classList.add('show');
            this.element.style.display = 'block';
            if (this.timeoutId) clearTimeout(this.timeoutId);
            this.timeoutId = setTimeout(() => this.hide(), this.delay);
        }

        hide() {
            if (!this.element) return;
            this.element.classList.remove('show');
            this.element.style.display = 'none';
        }
    }

    // Lightweight placeholder so existing tooltip init code keeps working.
    class Tooltip {
        constructor(element) {
            this.element = element;
        }
    }

    function toggleCollapse(button) {
        var targetSel = button.getAttribute('data-bs-target');
        var target = targetSel ? qs(targetSel) : null;
        if (!target) return;
        var willShow = !target.classList.contains('show');
        target.classList.toggle('show', willShow);
        button.setAttribute('aria-expanded', willShow ? 'true' : 'false');
    }

    function closeAllDropdowns() {
        qsa('.dropdown-menu.show').forEach(function (menu) {
            menu.classList.remove('show');
        });
    }

    function toggleDropdown(button) {
        var menu = button.nextElementSibling;
        if (!menu || !menu.classList.contains('dropdown-menu')) return;
        var willShow = !menu.classList.contains('show');
        closeAllDropdowns();
        if (willShow) menu.classList.add('show');
    }

    function openModalBySelector(selector) {
        var element = qs(selector);
        if (!element) return;
        Modal.getOrCreateInstance(element).show();
    }

    function closeClosest(element, type) {
        var target = element.closest('.' + type);
        if (!target) return;
        if (type === 'modal') {
            Modal.getOrCreateInstance(target).hide();
        } else if (type === 'toast') {
            new Toast(target).hide();
        }
    }

    function closeNavbarOnLinkClick(event) {
        var link = event.target.closest('.app-navbar-collapse .nav-link');
        if (!link) return;
        if (window.innerWidth > 991) return;

        var navbarCollapse = qs('#navbarNav');
        var toggler = qs('.navbar-toggler[data-bs-target="#navbarNav"]');
        if (!navbarCollapse || !navbarCollapse.classList.contains('show')) return;

        navbarCollapse.classList.remove('show');
        if (toggler) toggler.setAttribute('aria-expanded', 'false');
    }

    function runServiceTest(button) {
        var url = button.getAttribute('data-service-test-url');
        var targetSel = button.getAttribute('data-service-test-target');
        var target = targetSel ? qs(targetSel) : null;
        if (!url || button.dataset.loading === '1') return;

        var originalHtml = button.innerHTML;
        button.dataset.loading = '1';
        button.disabled = true;
        button.innerHTML = '<span class="ui-icon">⏳</span> Testing...';
        if (target) {
            target.classList.remove('text-danger', 'text-success');
            target.classList.add('text-muted');
            target.textContent = 'Running test...';
        }

        fetch(url, {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
            .then(function (response) {
                return response.json().catch(function () { return {}; }).then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (result) {
                if (!target) return;
                target.classList.remove('text-muted', 'text-danger', 'text-success');
                if (result.ok && result.data.ok) {
                    target.classList.add('text-success');
                    target.textContent = result.data.message || 'Service connection successful.';
                } else {
                    target.classList.add('text-danger');
                    target.textContent = result.data.message || 'Service test failed.';
                }
            })
            .catch(function () {
                if (!target) return;
                target.classList.remove('text-muted', 'text-success');
                target.classList.add('text-danger');
                target.textContent = 'Network error while running service test.';
            })
            .finally(function () {
                button.dataset.loading = '0';
                button.disabled = false;
                button.innerHTML = originalHtml;
            });
    }

    document.addEventListener('click', function (event) {
        closeNavbarOnLinkClick(event);

        var serviceTestButton = event.target.closest('[data-service-test-url]');
        if (serviceTestButton) {
            event.preventDefault();
            runServiceTest(serviceTestButton);
            return;
        }

        var toggle = event.target.closest('[data-bs-toggle]');
        if (toggle) {
            var mode = toggle.getAttribute('data-bs-toggle');
            if (mode === 'collapse') {
                event.preventDefault();
                toggleCollapse(toggle);
            } else if (mode === 'dropdown') {
                event.preventDefault();
                toggleDropdown(toggle);
            } else if (mode === 'modal') {
                event.preventDefault();
                openModalBySelector(toggle.getAttribute('data-bs-target'));
            }
        }

        var dismiss = event.target.closest('[data-bs-dismiss]');
        if (dismiss) {
            var dismissType = dismiss.getAttribute('data-bs-dismiss');
            if (dismissType === 'modal' || dismissType === 'toast') {
                event.preventDefault();
                closeClosest(dismiss, dismissType);
            }
        }

        if (!event.target.closest('.dropdown')) {
            closeAllDropdowns();
        }

        if (event.target.classList.contains('modal-backdrop')) {
            qsa('.modal.show').forEach(function (modalEl) {
                new Modal(modalEl).hide();
            });
        }
    });

    window.bootstrap = {
        Modal: Modal,
        Toast: Toast,
        Tooltip: Tooltip,
    };
})();

