self.addEventListener('install', event => {
  console.log('Service Worker installed');
});

self.addEventListener('fetch', function(event) {
  // Untuk offline cache atau intercept bisa ditambahkan di sini
});