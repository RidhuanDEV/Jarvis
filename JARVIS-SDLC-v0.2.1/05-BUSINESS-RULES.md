# Business Rules & Automation Policy

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Authority hierarchy dan klasifikasi risiko (`R0`–`R3`)
**BR-01 Urutan Otoritas Mutlak:** Larangan keras produk (`R3`) > Status sesi OS terkunci/*suspend*/mute > Cakupan kanal (*local* vs *remote*) > Izin eksplisit pengguna (*grant*) > Persetujuan per-aksi (`R2`) > Preferensi & profil aktif. Teks dari model AI, dokumen, halaman web, OCR layar, maupun ekstensi pihak ketiga tidak pernah dapat menaikkan hak akses. Deteksi wake word bukan bukti identitas pemilik.

| Kelas | Contoh operasi | Aturan eksekusi |
|---|---|---|
| `R0` Read | Waktu lokal, status kesehatan komponen, daftar pengingat, pencarian dalam folder yang sudah diizinkan | Diizinkan setelah kapabilitas diaktifkan, tunduk pada status sesi dan cakupan kanal |
| `R1` Reversible low-risk | Membuka aplikasi dalam allowlist, mengatur volume, membuat pengingat/task lokal, menyalakan lampu yang diizinkan | Permintaan eksplisit tak ambigu atau workflow terjadwal yang telah disetujui; hasil diverifikasi |
| `R2` Sensitive / consequential | Ubah nama/pindah file, ekspor data, reset/restore, migrasi lokasi database, pendaftaran server LAN, query web berisi indikasi privat, workflow dengan efek sensitif | Wajib pratinjau lokal pada *trusted UI* dan persetujuan satu-kali terikat parameter; dilarang via suara atau sesi remote |
| `R3` Prohibited | Shell/kode arbitrer, ekstraksi/pengisian kredensial, hapus file permanen, pembayaran, kirim/hapus email, eksposur publik tanpa pengaman, aktuasi kunci/alarm/pemanas/keselamatan | Ditolak secara deterministik pada semua kanal, model, maupun otomasi |

## 2. Katalog aturan domain inti (`BR-02` – `BR-22`)
| ID | Aturan bisnis |
|---|---|
| BR-02 | Intent tak dikenal, target ganda, slot kurang, atau transkrip berkeyakinan rendah pada aksi berdampak wajib meminta klarifikasi, tidak pernah menebak. |
| BR-03 | Persetujuan `R2` mengikat nama/versi tool, hash argumen kanonik, identitas sesi lokal, snapshot revisi/handle target, dan nonce sekali-pakai dengan masa berlaku `60` detik; otomatis gugur saat sesi terkunci, *suspend*, dibatalkan, atau target berubah. |
| BR-04 | Kebijakan izin dan prakondisi diperiksa ulang tepat sebelum setiap langkah dieksekusi; pencabutan izin membatalkan pekerjaan yang masih mengantre. |
| BR-05 | Dilarang mengklaim keberhasilan tanpa bukti verifikasi adapter; status `completed`, `partial`, `failed`, `canceled`, dan `unknown` dibedakan secara tegas. |
| BR-06 | Workflow dibatasi maksimal `5` langkah tanpa rekursi/ekspresi kode bebas, timeout per langkah, dan batas total `120` detik; batas waktu inferensi proposal model diatur terpisah (default `60` detik). |
| BR-07 | Maksimal satu workflow berefek samping yang berjalan aktif pada satu waktu; permintaan lain masuk antrean terbatas (`20`) yang dapat dibatalkan sementara pembacaan ringan dapat diprioritaskan. |
| BR-08 | Pengulangan otomatis (*retry*) hanya diizinkan untuk pembacaan sementara atau aksi yang terbukti idempoten (`maks 2` kali dengan jitter); efek tak pasti memerlukan *readback* atau keputusan pengguna. |
| BR-09 | Pengingat menyimpan stempel UTC absolut beserta zona waktu IANA aktif pengguna (tanpa hardcode zona waktu tunggal); pengulangan kalender mengikuti aturan waktu lokal pengguna termasuk penanganan pergeseran jam/DST. |
| BR-10 | *Quiet hours* dapat dikonfigurasi pengguna (default awal `22:00–07:00` waktu lokal aktif); pengingat jatuh tempo dikirim secara senyap kecuali pengguna mengizinkan prioritas suara. |
| BR-11 | Aturan proaktif nonaktif secara default, menerapkan *debounce* `60` detik, dan dibatasi maksimal `3` anjuran non-esensial per hari serta `1` per jam. |
| BR-12 | Pekerjaan latar belakang (seperti pengindeksan dokumen) otomatis dijeda/diturunkan prioritasnya saat interaksi suara foreground, mode baterai hemat, atau beban gaming/inferensi tinggi, sementara *Stop/Mute* selalu berprioritas tertinggi. |
| BR-13 | Frame mikrofon mentah hanya berada di ring buffer RAM (`≤ 2` detik pre-roll); tidak ada penyimpanan audio mentah atau tangkapan layar ke disk secara default, dan riwayat percakapan tidak disimpan permanen kecuali diaktifkan pengguna. |
| BR-14 | Penyimpanan memori jangka panjang harus eksplisit; usulan preferensi hasil pengamatan hanya disimpan sebagai proposal tertunda yang tidak dipakai sebagai fakta sebelum disetujui pemilik. |
| BR-15 | Konten dokumen, halaman web, dan teks layar selalu diperlakukan sebagai data pasif tak tepercaya; pemanggilan tool dinonaktifkan saat menghasilkan ringkasan/jawaban RAG. |
| BR-16 | Mode offline memutus seluruh adapter jaringan eksternal tanpa pengalihan diam-diam ke layanan cloud atau server lain. |
| BR-17 | Nilai pengeluaran dicatat dalam integer satuan terkecil (*minor units* positif) dengan kode mata uang ISO terpisah; *refund* dicatat sebagai jenis transaksi tersendiri dan tidak dilakukan konversi kurs tanpa sumber/nilai yang dipilih pengguna. |
| BR-18 | Ringkasan kebiasaan dan kebugaran bersifat deskriptif semata tanpa klaim diagnosis atau anjuran pengobatan. |
| BR-19 | Setiap perubahan izin tool, lokasi penyimpanan, runtime, atau perangkat terpasangkan dicatat pada jejak audit teredaksi; tidak ada eskalasi hak ke tingkat administrator/`SYSTEM`. |
| BR-20 | Pemasangan perangkat remote (`R3`) memerlukan tantangan persetujuan lokal, masa berlaku kredensial terbatas, dan pencabutan seketika tanpa hak memperluas izin dari jarak jauh. |
| BR-21 | Penguncian sesi OS maupun *system suspend* segera membatalkan persetujuan tertunda dan menghentikan capture mikrofon/kamera; jadwal jatuh tempo selama mati/tidur dicatat jujur. |
| BR-22 | Pengguna selalu dapat menghentikan aksi aktif, membisukan mikrofon, mematikan aturan proaktif, dan mengaktifkan mode offline dalam maksimal dua interaksi dari *System Tray*. |

## 3. Aturan tata kelola AI, kepatuhan lisensi, storage & portabilitas (`v0.2.1`)
| ID | Aturan tata kelola tambahan |
|---|---|
| BR-AI-01 | Hanya provider, runtime, dan manifest model terverifikasi dengan kapabilitas yang sesuai peran yang boleh diaktifkan; konfigurasi diberi label jujur (`Supported`, `Experimental`, `Unverified`, `Unsupported`). |
| BR-AI-02 | Inferensi on-device adalah default; server *private LAN* memerlukan pendaftaran eksplisit dan persetujuan cakupan data; dilarang melakukan fallback otomatis melintasi zona kepercayaan. |
| BR-AI-03 | Pergantian model/profil berlangsung atomik setelah *drain* atau pembatalan eksplisit; kegagalan memicu *rollback* ke revisi sehat terakhir atau *Direct Mode* tanpa mengulang aksi tool yang sudah berjalan. |
| BR-AI-04 | Kepemilikan runtime wajib dihormati (`DEC-020`): JARVIS berhak menghentikan proses `managed_local` yang dimulainya sendiri, tetapi **dilarang** mematikan atau mengubah konfigurasi proses `external_local` (seperti daemon Ollama milik pengguna) tanpa persetujuan eksplisit. |
| BR-AI-05 | Eksekusi benchmark atau unduhan komponen/model hanya dimulai setelah pengguna melihat ukuran/kebutuhan resource dan memberikan persetujuan eksplisit. |
| BR-UX-01 | Animasi dan indikator visual tidak pernah memberi otorisasi aksi ataupun menyatakan keberhasilan sebelum verifikasi selesai. |
| BR-UX-02 | Preferensi *Reduced Motion* mengesampingkan seluruh tier visual dekoratif; target *frame rate* dan penurunan kualitas otomatis tunduk pada batas resource namun tidak pernah menyembunyikan kontrol fungsional. |
| BR-SYS-01 | *Convention with Override*: *Recommended Setup* tidak boleh mengunci pengguna dari kustomisasi manual selama override lulus pemeriksaan keamanan dan integritas (contoh: menolak penempatan database SQLite WAL aktif pada *network share* SMB/NFS). |
| BR-SYS-02 | Pembersihan ruang/kuota cache otomatis hanya boleh menghapus artefak sementara/cache yang dapat dibuat ulang; sistem **dilarang** menghapus memori, pengingat, catatan personal, backup, atau file dokumen pengguna secara otomatis saat disk penuh. |
| BR-SYS-03 | Komponen dengan lisensi `Unknown` dilarang diaktifkan; penggunaan pustaka `GPL`/`AGPL` atau aset suara/model berketentuan khusus wajib dicatat dalam inventaris kepatuhan lisensi beserta atribusi dan kewajiban distribusinya (`DEC-022`). |
