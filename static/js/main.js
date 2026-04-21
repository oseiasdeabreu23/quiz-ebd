// EBD Digital — main.js

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', () => {
  const flashes = document.querySelectorAll('.flash');
  flashes.forEach(f => {
    setTimeout(() => {
      f.style.opacity = '0';
      f.style.transition = 'opacity .4s';
      setTimeout(() => f.remove(), 400);
    }, 5000);
  });

  // Confirm forms with data-confirm attribute
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('submit', e => {
      if (!confirm(el.dataset.confirm)) e.preventDefault();
    });
  });

  // Format matrícula input
  const matriculaInput = document.querySelector('input[name="matricula"]');
  if (matriculaInput) {
    matriculaInput.addEventListener('input', () => {
      matriculaInput.value = matriculaInput.value.toUpperCase();
    });
  }
});
