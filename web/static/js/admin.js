// Admin panel JavaScript functionality
class AdminPanel {
    constructor() {
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.startStatusUpdates();
    }

    setupEventListeners() {
        document.addEventListener('DOMContentLoaded', () => {
            this.updateSystemStatus();
        });

        this.setupFormValidations();
        this.setupToastNotifications();
    }

    async updateSystemStatus() {
        try {
            const response = await fetch('/admin/system/status');
            const status = await response.json();

            const statusElement = document.getElementById('system-status');
            if (!statusElement) {
                return;
            }

            if (status.bridge.status === 'ok') {
                statusElement.innerHTML =
                    '<i class="fas fa-circle text-success"></i> Система онлайн';
            } else if (status.bridge.status === 'offline') {
                statusElement.innerHTML =
                    '<i class="fas fa-circle text-warning"></i> Bridge офлайн';
            } else {
                statusElement.innerHTML =
                    '<i class="fas fa-circle text-danger"></i> Ошибка системы';
            }
        } catch (error) {
            const statusElement = document.getElementById('system-status');
            if (statusElement) {
                statusElement.innerHTML =
                    '<i class="fas fa-circle text-danger"></i> Нет связи';
            }
            console.error('Status update error:', error);
        }
    }

    startStatusUpdates() {
        setInterval(() => {
            this.updateSystemStatus();
        }, 30000);
    }

    setupFormValidations() {
        const forms = document.querySelectorAll('form[data-validate]');
        forms.forEach((form) => {
            form.addEventListener('submit', (e) => {
                if (!this.validateForm(form)) {
                    e.preventDefault();
                }
            });
        });
    }

    validateForm(form) {
        let isValid = true;
        const inputs = form.querySelectorAll('input[required], select[required]');

        inputs.forEach((input) => {
            if (!input.value.trim()) {
                this.showFieldError(input, 'Это поле обязательно для заполнения');
                isValid = false;
            } else {
                this.clearFieldError(input);
            }
        });

        const emailInputs = form.querySelectorAll('input[type="email"]');
        emailInputs.forEach((input) => {
            if (input.value && !this.isValidEmail(input.value)) {
                this.showFieldError(input, 'Введите корректный email адрес');
                isValid = false;
            }
        });

        return isValid;
    }

    isValidEmail(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }

    showFieldError(input, message) {
        input.classList.add('is-invalid');

        let errorElement = input.parentNode.querySelector('.invalid-feedback');
        if (!errorElement) {
            errorElement = document.createElement('div');
            errorElement.className = 'invalid-feedback';
            input.parentNode.appendChild(errorElement);
        }

        errorElement.textContent = message;
    }

    clearFieldError(input) {
        input.classList.remove('is-invalid');
        const errorElement = input.parentNode.querySelector('.invalid-feedback');
        if (errorElement) {
            errorElement.remove();
        }
    }

    setupToastNotifications() {
        if (!document.getElementById('toast-container')) {
            const container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast-container position-fixed top-0 end-0 p-3';
            container.style.zIndex = '1060';
            document.body.appendChild(container);
        }
    }

    showToast(message, type = 'info') {
        const toastId = 'toast-' + Date.now();
        const toastHtml = `
            <div class="toast align-items-center text-white bg-${type}" role="alert" id="${toastId}">
                <div class="d-flex">
                    <div class="toast-body">
                        ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
            </div>
        `;

        const container = document.getElementById('toast-container');
        container.insertAdjacentHTML('beforeend', toastHtml);

        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement, { delay: 5000 });
        toast.show();

        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });
    }
}

const adminPanel = new AdminPanel();
