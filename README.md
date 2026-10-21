# ResQNet

**AI-Powered Disaster Preparedness & Response Coordination Platform**

ResQNet is a web-based platform designed to simplify disaster reporting, emergency assistance coordination, and access to preparedness information.

It connects citizens, volunteers, NGOs, and administrators through a centralized system with role-based dashboards, interactive maps, AI-powered guidance, and weather information.

**[Live Website](https://resqnet2026.netlify.app)** · **[Backend API](https://resqnet2.onrender.com/health)**

> **Note:** ResQNet is a developing platform, not an official emergency dispatch or disaster warning service.

---

## Features

### Disaster Reporting & Assistance
- Submit disaster incident reports with location details and supporting images.
- Request assistance for rescue, food, water, shelter, or medical needs.
- Track the status of submitted requests.
- Manage reports and assistance workflows through role-based dashboards.

### Role-Based Dashboards

| Role | Capabilities |
|---|---|
| Citizen | Report incidents, request assistance, track requests |
| Volunteer | View assigned tasks, update progress |
| NGO | Coordinate resources and relief activities |
| Admin | Manage reports, users, requests, and analytics |

### AI-Powered Chatbot

Powered by **Groq**, the ResQNet chatbot provides conversational guidance about disaster preparedness and safety.

- Natural-language conversations
- Disaster preparedness information
- Suggested questions and responsive chat interface
- Typing indicators and message timestamps
- Server-side API integration
- Input validation and rate limiting

The chatbot provides informational assistance only. It does not independently verify emergencies or dispatch rescue services.

### Weather Dashboard

Integrated with **OpenWeather** to display available weather observations:

- Temperature and weather conditions
- Humidity and wind speed
- Reported rainfall, when available
- Location-specific weather information
- Loading and error handling

### Interactive Maps

Built with **Leaflet.js and OpenStreetMap**.

- Geographic visualization of authorized incident data
- Location-based reporting
- Interactive map controls
- Privacy-aware access to incident information

### Analytics & Statistics

- Database-backed homepage statistics
- Incident and assistance request tracking
- Administrative analytics
- Dynamic updates from backend APIs
- Empty-data handling without fabricated statistics

---

## Flood Intelligence

ResQNet also includes a developing Flood Intelligence capability focused on satellite-based flood analysis and infrastructure exposure.

The analytical workflow uses:

- Sentinel-1 SAR imagery
- Sentinel-2 optical imagery
- Copernicus elevation data
- Geospatial change detection
- Terrain and persistent-water filtering
- OpenStreetMap infrastructure data
- Road network exposure analysis

**Processing workflow:**

```text
Satellite Imagery
       |
       v
Preprocessing
       |
       v
SAR Change Detection
       |
       v
Terrain & Water Filtering
       |
       v
Flood Candidate Mapping
       |
       v
Optical Evidence Assessment
       |
       v
Infrastructure Exposure Analysis
       |
       v
Scientific Review & Visualization
```

Flood Intelligence currently operates as a separate analytical prototype. Its outputs are exploratory flood candidates, not independently confirmed inundation maps. Integration into the live ResQNet dashboard remains a planned enhancement.

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python, Flask, REST APIs |
| Database | Supabase PostgreSQL |
| ORM | SQLAlchemy |
| Storage | Supabase Storage |
| Authentication | JWT, bcrypt |
| AI | Groq API |
| Weather | OpenWeather API |
| Maps | Leaflet.js, OpenStreetMap |
| Rate Limiting | Redis |
| Deployment | Netlify, Render |

---

## Architecture

```text
                  USERS
                    |
      +-------------+-------------+
      |             |             |
   Citizens     Volunteers     NGOs / Admins
      |             |             |
      +-------------+-------------+
                    |
                    v
             FRONTEND (Netlify)
             HTML / CSS / JS
                    |
                    v
             BACKEND (Render)
                Flask API
                    |
      +-------------+-------------+
      |             |             |
      v             v             v
 Authentication  Core Services  Integrations
      |             |             |
      |       Reports / SOS       +---- Groq AI
      |       Tasks / Stats       +---- OpenWeather
      |       NGO Management      +---- OpenStreetMap
      |             |
      +------+------+ 
             |
      +------+------+
      |             |
      v             v
   Supabase       Redis
 PostgreSQL &   Rate Limiting
 Private Storage
```

The Flood Intelligence processing pipeline is maintained separately from the live application backend.

---

## Getting Started

### Prerequisites

- Python 3.x
- Git
- Access to a configured PostgreSQL database
- Required API credentials

### 1. Clone the Repository

```bash
git clone https://github.com/susmitha1802/resqnet2.git
cd resqnet2
```

### 2. Install Backend Dependencies

```bash
pip install -r backend/requirements.txt
```

### 3. Configure Environment Variables

Create `backend/.env` using `backend/.env.example` as a reference.

```env
DATABASE_URL=your_postgresql_connection_string
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-20b
OPENWEATHER_API_KEY=your_openweather_api_key
CORS_ORIGINS=http://127.0.0.1:5500
PROXY_DIAGNOSTIC_ENABLED=False
```

Additional authentication, storage, and rate-limiting settings may be required. Refer to `backend/.env.example` and `DEPLOYMENT.md`.

Never commit API keys or `.env` files.

### 4. Start the Backend

```bash
python -B backend/app.py
```

### 5. Start the Frontend

Open another terminal:

```bash
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Visit:

http://127.0.0.1:5500

---

## Security

ResQNet includes:

- JWT-based authentication
- Role-based access control
- bcrypt password hashing
- Request validation
- API rate limiting
- Restricted CORS origins
- Private file storage
- Server-side API credential management

Security configuration should be reviewed before production deployment.

---

## Testing

The latest reported local test results:

| Test Suite | Result |
|---|---|
| Backend | 148 passed |
| Frontend | 92 passed |
| Responsive UI | Passed local browser checks |
| Role-based workflows | Passed local smoke checks |
| Groq API | Successful local response |

Live weather and newly deployed application features require separate production verification.

---

## Deployment

| Service | Platform |
|---|---|
| Frontend | Netlify |
| Backend | Render |
| Database | Supabase PostgreSQL |
| File Storage | Supabase Storage |

Production secrets are configured through the backend hosting environment.

See `DEPLOYMENT.md` for deployment configuration and verification instructions.



## Disclaimer

ResQNet is a developing disaster preparedness and coordination platform. It is not a substitute for official emergency services, verified disaster alerts, or professional emergency guidance.

---

**ResQNet — Connecting Communities. Coordinating Response.**
