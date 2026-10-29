# MarTube

MarTube adalah aplikasi untuk menonton dan mengunduh film atau serial dari IDLIX. Aplikasinya berjalan di komputer kamu sendiri dan dibuka lewat browser, tampilannya mirip Apple TV.

Yang bisa dilakukan:

1. Cari film atau serial, lalu tonton langsung tanpa iklan.
2. Unduh film atau episode, beberapa sekaligus, lengkap dengan subtitle.
3. Simpan judul ke Watch Later dan lanjutkan tontonan dari posisi terakhir.
4. Ikuti serial favorit dan dapat kabar kalau ada episode baru.
5. Tonton dalam kualitas 1080p kalau kamu masuk dengan akun IDLIX.

## Yang perlu disiapkan

Kamu butuh Windows dan Python 3.12 yang diunduh dari [python.org](https://www.python.org/downloads/). Saat memasang Python, centang pilihan "Add Python to PATH". FFmpeg tidak perlu dipasang sendiri karena aplikasi akan mengunduhnya otomatis saat pertama kali dijalankan.

## Cara memasang

Buka PowerShell, lalu jalankan perintah ini satu per satu:

```powershell
git clone https://github.com/marcaroon/movie-stream.git
cd movie-stream
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Setelah itu buat shortcut MarTube di Desktop dan Start Menu:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_shortcuts.ps1
```

## Cara memakai

Klik shortcut MarTube di Desktop. Aplikasi akan berjalan di belakang layar dan browser akan terbuka di http://127.0.0.1:8765.

Kalau tidak mau memakai shortcut, kamu juga bisa menjalankannya dari folder proyek:

```powershell
.\.venv\Scripts\pythonw.exe launcher.py
```

Unduhan tetap berjalan walaupun tab browser ditutup. Untuk mematikan aplikasi sepenuhnya, buka halaman Downloads lalu klik Quit.

Hasil unduhan tersimpan di folder `Downloads` di dalam folder proyek. Lokasinya bisa diganti dari halaman Downloads.

## Kualitas 1080p

Tanpa akun, IDLIX hanya memberi kualitas sampai 720p. Supaya dapat 1080p, klik ikon akun di kanan atas lalu masuk dengan akun IDLIX kamu. Akun gratis pun sudah cukup.

Password kamu langsung dikirim ke IDLIX dan tidak pernah disimpan. MarTube hanya menyimpan sesi login dalam bentuk terenkripsi di komputer kamu.

## Kalau ada masalah

Kalau port 8765 sudah dipakai program lain, ganti nilai `"port"` di file `%APPDATA%\IdlixDownloader\settings.json`.

Kalau folder proyek dipindah, jalankan lagi perintah pembuatan shortcut di atas supaya shortcut mengarah ke lokasi yang baru.

Catatan error tersimpan di `%LOCALAPPDATA%\IdlixDownloader\logs\idlix.log`. File ini berguna untuk dicek kalau ada unduhan yang gagal.

## Versi command line

Kalau lebih suka lewat terminal, versi lamanya masih ada:

```powershell
.\.venv\Scripts\python.exe main.py
```

## Catatan

Proyek ini dikembangkan dari [IdlixDownloader](https://github.com/sandrocods/IdlixDownloader) milik sandrocods. Dibuat untuk belajar, jadi gunakan dengan bijak. Segala penyalahgunaan di luar tanggung jawab pembuat.
