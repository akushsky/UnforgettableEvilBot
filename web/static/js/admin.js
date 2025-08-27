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
        // Auto-refresh system status
        document.addEventListener('DOMContentLoaded', () => {
            this.updateSystemStatus();
        });

        // Form validations
        this.setupFormValidations();

        // Toast notifications
        this.setupToastNotifications();
    }

    // System status updates
    async updateSystemStatus() {
        try {
            const response = await fetch('/admin/system/status');
            const status = await response.json();

            const statusElement = document.getElementById('system-status');
            const bridgeClientsElement = document.getElementById('bridge-clients');

            if (status.bridge.status === 'ok') {
                statusElement.innerHTML = '<i class="fas fa-circle text-success"></i> Система онлайн';
                if (bridgeClientsElement && status.bridge.clients !== undefined) {
                    bridgeClientsElement.textContent = status.bridge.clients;
                }
            } else if (status.bridge.status === 'offline') {
                statusElement.innerHTML = '<i class="fas fa-circle text-warning"></i> Bridge офлайн';
            } else {
                statusElement.innerHTML = '<i class="fas fa-circle text-danger"></i> Ошибка системы';
            }
        } catch (error) {
            const statusElement = document.getElementById('system-status');
            statusElement.innerHTML = '<i class="fas fa-circle text-danger"></i> Нет связи';
            console.error('Status update error:', error);
        }
    }

    startStatusUpdates() {
        // Update status every 30 seconds
        setInterval(() => {
            this.updateSystemStatus();
        }, 30000);
    }

    // Form validations
    setupFormValidations() {
        const forms = document.querySelectorAll('form[data-validate]');
        forms.forEach(form => {
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

        inputs.forEach(input => {
            if (!input.value.trim()) {
                this.showFieldError(input, 'Это поле обязательно для заполнения');
                isValid = false;
            } else {
                this.clearFieldError(input);
            }
        });

        // Email validation
        const emailInputs = form.querySelectorAll('input[type="email"]');
        emailInputs.forEach(input => {
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

    // Toast notifications
    setupToastNotifications() {
        // Create toast container if it doesn't exist
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

        // Remove toast element after it's hidden
        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });
    }

    // WhatsApp QR Code management
    async generateQRCode(userId) {
        try {
            const qrContainer = document.getElementById('qr-container');
            const progressBar = document.getElementById('qr-progress');
            const generateBtn = document.getElementById('generate-qr-btn');

            // Показываем прогресс-бар
            if (progressBar) {
                progressBar.style.display = 'block';
                const progressBarInner = progressBar.querySelector('.progress-bar');
                progressBarInner.style.width = '50%';
            }

            // Отключаем кнопку
            if (generateBtn) {
                generateBtn.disabled = true;
                generateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Генерация...';
            }

            this.showToast('Инициализация WhatsApp клиента...', 'info');

            const response = await fetch(`/admin/users/${userId}/qr`);
            const result = await response.json();

            if (result.status === 'success') {
                // Обновляем прогресс-бар
                if (progressBar) {
                    const progressBarInner = progressBar.querySelector('.progress-bar');
                    progressBarInner.style.width = '100%';
                }

                // Отображаем QR-код
                this.displayQRCode(result.qr_code);
                this.showToast('QR-код готов! Отсканируйте его в WhatsApp.', 'success');

                // Запускаем проверку статуса подключения
                this.startConnectionStatusCheck(userId);

            } else if (result.status === 'pending') {
                this.showToast('QR-код генерируется... Повторная попытка через 3 секунды.', 'warning');

                // Повторяем попытку через 3 секунды
                setTimeout(() => {
                    this.retryQRCodeGeneration(userId);
                }, 3000);
            } else {
                this.showToast('Ошибка: ' + result.message, 'danger');
            }

        } catch (error) {
            this.showToast('Ошибка подключения: ' + error.message, 'danger');
        } finally {
            // Скрываем прогресс-бар
            const progressBar = document.getElementById('qr-progress');
            if (progressBar) {
                setTimeout(() => {
                    progressBar.style.display = 'none';
                }, 1000);
            }

            // Восстанавливаем кнопку
            const generateBtn = document.getElementById('generate-qr-btn');
            if (generateBtn) {
                generateBtn.disabled = false;
                generateBtn.innerHTML = '<i class="fas fa-sync"></i> Обновить QR-код';
            }
        }
    }

    async retryQRCodeGeneration(userId, attempts = 0) {
        const maxAttempts = 5;

        if (attempts >= maxAttempts) {
            this.showToast('Не удалось получить QR-код после нескольких попыток', 'danger');
            return;
        }

        try {
            const response = await fetch(`/admin/users/${userId}/qr/check`);
            const result = await response.json();

            if (result.status === 'ready') {
                this.displayQRCode(result.qr_code);
                this.showToast('QR-код готов!', 'success');
                this.startConnectionStatusCheck(userId);
            } else {
                setTimeout(() => {
                    this.retryQRCodeGeneration(userId, attempts + 1);
                }, 2000);
            }
        } catch (error) {
            this.showToast('Ошибка при получении QR-кода: ' + error.message, 'danger');
        }
    }

    displayQRCode(qrCodeDataUrl) {
        const qrContainer = document.getElementById('qr-container');

        const qrHtml = `
            <div class="qr-code-display">
                <img src="${qrCodeDataUrl}" alt="WhatsApp QR Code" class="img-fluid mb-3" style="max-width: 300px;">
                <div class="qr-actions">
                    <button class="btn btn-primary me-2" onclick="adminPanel.copyQRToClipboard('${qrCodeDataUrl}')">
                        <i class="fas fa-copy"></i> Копировать в буфер
                    </button>
                    <button class="btn btn-success me-2" onclick="adminPanel.downloadQRCode('${qrCodeDataUrl}')">
                        <i class="fas fa-download"></i> Скачать
                    </button>
                    <button class="btn btn-info" data-bs-toggle="modal" data-bs-target="#sendQRModal">
                        <i class="fas fa-envelope"></i> Отправить клиенту
                    </button>
                </div>
                <div class="mt-3">
                    <small class="text-muted">
                        <i class="fas fa-info-circle"></i>
                        Откройте WhatsApp на телефоне → Настройки → Связанные устройства → Привязать устройство
                    </small>
                </div>
            </div>
        `;

        qrContainer.innerHTML = qrHtml;
    }

    async copyQRToClipboard(qrCodeDataUrl) {
        try {
            // Конвертируем Data URL в blob
            const response = await fetch(qrCodeDataUrl);
            const blob = await response.blob();

            // Создаем ClipboardItem
            const clipboardItem = new ClipboardItem({ [blob.type]: blob });

            // Копируем в буфер обмена
            await navigator.clipboard.write([clipboardItem]);

            this.showToast('QR-код скопирован в буфер обмена!', 'success');
        } catch (error) {
            // Fallback для старых браузеров - копируем как текст
            try {
                await navigator.clipboard.writeText(qrCodeDataUrl);
                this.showToast('Ссылка на QR-код скопирована в буфер обмена!', 'success');
            } catch (fallbackError) {
                this.showToast('Не удалось скопировать в буфер обмена', 'warning');
                console.error('Clipboard error:', error, fallbackError);
            }
        }
    }

    downloadQRCode(qrCodeDataUrl) {
        try {
            const link = document.createElement('a');
            link.href = qrCodeDataUrl;
            link.download = `whatsapp-qr-${Date.now()}.png`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showToast('QR-код загружен!', 'success');
        } catch (error) {
            this.showToast('Ошибка при загрузке QR-кода', 'danger');
        }
    }

    startConnectionStatusCheck(userId) {
        let checkCount = 0;
        const maxChecks = 60; // 5 минут при проверке каждые 5 секунд

        const statusInterval = setInterval(async () => {
            checkCount++;

            try {
                const response = await fetch(`/whatsapp/status`);
                const status = await response.json();

                if (status.whatsapp_connected) {
                    clearInterval(statusInterval);
                    this.showToast('WhatsApp успешно подключен!', 'success');

                    // Обновляем страницу через 2 секунды
                    setTimeout(() => {
                        location.reload();
                    }, 2000);
                }

            } catch (error) {
                console.error('Status check error:', error);
            }

            // Останавливаем проверку через 5 минут
            if (checkCount >= maxChecks) {
                clearInterval(statusInterval);
                this.showToast('Время ожидания истекло. Обновите страницу для проверки статуса.', 'warning');
            }

        }, 5000); // Проверяем каждые 5 секунд
    }

    // Chat management
    async loadAvailableChats(userId) {
        try {
            const response = await fetch(`/admin/users/${userId}/chats`);
            const result = await response.json();

            if (result.status === 'success') {
                return result.chats;
            } else {
                this.showToast('Ошибка загрузки чатов: ' + result.message, 'danger');
                return [];
            }
        } catch (error) {
            this.showToast('Ошибка подключения: ' + error.message, 'danger');
            return [];
        }
    }

    // Utility functions
    formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString('ru-RU', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
}

// Global functions for template usage
async function generateQRCode() {
    const userId = window.location.pathname.split('/').pop();
    await adminPanel.generateQRCode(userId);
}

async function refreshQRCode() {
    await generateQRCode();
}

async function checkWhatsAppStatus() {
    try {
        const response = await fetch('/whatsapp/status');
        const status = await response.json();

        if (status.whatsapp_connected) {
            adminPanel.showToast('WhatsApp подключен и работает!', 'success');
        } else {
            adminPanel.showToast('WhatsApp не подключен', 'warning');
        }
    } catch (error) {
        adminPanel.showToast('Ошибка проверки статуса: ' + error.message, 'danger');
    }
}

async function loadAvailableChats() {
    const userId = window.location.pathname.split('/').pop();
    const chats = await adminPanel.loadAvailableChats(userId);

    const container = document.getElementById('available-chats-container');
    if (chats.length > 0) {
        // Display chats logic here
        console.log('Available chats:', chats);
    }
}

async function downloadQRCode() {
    const qrImage = document.querySelector('.qr-code-display img');
    if (qrImage) {
        adminPanel.downloadQRCode(qrImage.src);
    } else {
        adminPanel.showToast('QR-код не найден', 'warning');
    }
}

// Initialize admin panel
const adminPanel = new AdminPanel();
