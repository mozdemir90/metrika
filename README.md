# METRİKA | Operasyonel Metrik ve Performans Raporlama Platformu

METRİKA; Belgenet GLPI REST API üzerinden servis masası çağrı verilerini çeken, SLA/performans metriklerini hesaplayan, kurum yöneticisi için responsive web dashboard'u sunan ve tek tıkla **kurumsal biçimlendirilmiş Excel raporu** üreten modüler bir **FastAPI + Kubernetes** mikroservisidir.

---

## 🌟 Öne Çıkan Özellikler

- **Strategy / Factory Tasarım Deseni**:
  - `BaseConnector` arayüzü ile GLPI, Mock, dosya yükleme ve gelecekte OpenProject, Jira veya SQL kaynaklarına tak-çalıştır genişletilebilirlik.
  - `BaseReport` arayüzü ile Servis Masası şablonunun yanı sıra yeni kurumsal rapor şablonları tanımlayabilme.
- **Servis Masası İş Kuralları & Metrik Motoru**:
  - **Teknisyen Adı Normalizasyonu**: GLPI'dan gelen `glpi \nİsim Soyisim` kirli verilerini temizler ve tekilleştirir.
  - **Süre Metni Dönüşümleri**: `"X gün Y saat Z dakika W saniye"` Türkçe metinlerini sayısal dakika ve saate çevirir.
  - **Net Çalışma Süresi**: `Net Efor = Toplam Çözüm Süresi - Dış Bekleme Süresi`. Kurumdan onay/bilgi beklenen süreler personelin net çözüm süresinden düşülür.
  - **SLA Uyum Oranları**:
    - MTTA (İlk Ele Alınma): Yüksek/Çok Yüksek $\le$ 30 dk, Diğerleri $\le$ 60 dk.
    - MTTR (Net Çözüm): Yüksek $\le$ 24 sa, Orta $\le$ 48 sa, Düşük $\le$ 72 sa.
  - **FCR (First Contact Resolution)**: OpenProject'e aktarılmadan doğrudan servis masasında çözülen taleplerin ayrıştırılması.
  - **Kalite Metriği (Reopen Rate)**: "Yeniden açıldı" etiketine sahip çağrıların oranı ve teknisyen bazlı dağılımı.
  - **Kök Neden & Kurum Dağılımı**: En çok çağrı açan ilk 10 kurumun Hata vs. Destek talebi kırılımı.
- **Kurumsal Excel Motoru (OpenPyXL)**:
  - Bellek içi (`io.BytesIO`) akış olarak Navy/Slate kurumsal renk paletiyle 4 sekmeli çıktı:
    1. *Özet Yönetici Paneli* (KPI Bilgi Kartları, SLA Matrisi, Excel formülleri)
    2. *Teknisyen Performansı* (SLA, efor ve kalite oranları)
    3. *Kurum & Kök Neden Analizi* (Hata vs Destek kırılımı)
    4. *Detaylı Çağrı Listesi* (Otomatik filtre, hizalamalar ve durum rozetleri)
- **Ham Excel / CSV Yükleme Desteği**:
  - Kullanıcı GLPI'dan aldığı ham Excel/CSV dosyasını arayüzden veya API'den tek tıkla yükleyebilir; sistem anında kolonları tanır, metrikleri hesaplar ve kurumsal biçimlendirilmiş Excel'e dönüştürür.
- **%100 Mobil Uyumlu Modern Dashboard**:
  - Tailwind CSS ve Chart.js ile telefonda, tablette ve masaüstünde kesintisiz yönetim paneli deneyimi.
- **On-Prem LLM Entegrasyon Altyapısı (`app/ai/`)**:
  - Kurum içi yerel LLM (Ollama, vLLM vb.) ile otomatik yönetici özeti, risk uyarıları ve eylem planı oluşturma altyapısı hazır.

---

## 📂 Klasör Yapısı

```
metrika/
├── app/
│   ├── core/
│   │   └── config.py             # Pydantic BaseSettings yapılandırması
│   ├── connectors/
│   │   ├── base_connector.py     # Soyut kaynak adaptörü
│   │   ├── glpi_connector.py     # GLPI REST API (Oturum, sayfalama, hata toleransı)
│   │   └── mock_connector.py     # Offline test ve simülasyon adaptörü
│   ├── reports/
│   │   ├── base_report.py        # Soyut rapor şablon sınıfı
│   │   ├── report_factory.py     # Rapor ve connector fabrikası
│   │   └── service_desk_report.py# Metrik hesaplama + OpenPyXL Excel çizim motoru
│   ├── ai/
│   │   └── executive_insights.py # Kural tabanlı ve On-Prem LLM yönetici özeti
│   ├── templates/
│   │   └── dashboard.html        # Responsive yönetici paneli (Tailwind + Chart.js)
│   ├── api/
│   │   └── routes.py             # Metrik, Excel export ve Upload uç noktaları
│   └── main.py                   # FastAPI uygulaması & sağlık kontrolleri
├── k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── tests/
│   ├── test_service_desk_report.py
│   └── test_api.py
├── Dockerfile
└── requirements.txt
```

---

## 🚀 Hızlı Başlangıç

### 1. Yerel Kurulum (Lokal Test)

```bash
# Sanal ortam oluşturma ve aktivasyon
python3.11 -m venv venv
source venv/bin/activate

# Bağımlılıkların yüklenmesi
pip install -r requirements.txt

# Uygulamanın başlatılması
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Arayüze erişim: [http://localhost:8000](http://localhost:8000)  
Swagger API Dokümantasyonu: [http://localhost:8000/docs](http://localhost:8000/docs)

### 2. Testlerin Çalıştırılması

```bash
pytest -v
```

---

## 📡 API Uç Noktaları

| Yöntem | Endpoint | Açıklama |
|---|---|---|
| `GET` | `/` | Responsive Yönetici Dashboard'u |
| `GET` | `/health` | Kubernetes Liveness/Readiness sağlık kontrolü |
| `GET` | `/api/v1/reports/types` | Kayıtlı rapor şablonları ve veri kaynakları listesi |
| `GET` | `/api/v1/reports/{type}/metrics?days=7&source=glpi` | JSON metrikleri ve akıllı yönetici özeti |
| `GET` | `/api/v1/reports/{type}/export-excel?days=7&source=glpi` | Biçimlendirilmiş kurumsal Excel (`.xlsx`) akışı |
| `POST`| `/api/v1/reports/{type}/upload` | Ham Excel/CSV yükleme ve anında metrik hesaplama |
| `POST`| `/api/v1/reports/{type}/export-from-upload` | Yüklenen ham dosyayı kurumsal Excel'e dönüştürüp indirme |

---

## ☸️ Kubernetes Dağıtımı

```bash
# 1. Namespace oluşturma
kubectl apply -f k8s/namespace.yaml

# 2. ConfigMap ve Secret uygulama
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml

# 3. Deployment ve Service uygulama
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```
