# LeadFlow AI 🚀

LeadFlow AI is an end-to-end AI Lead Generation and Outreach Agent built with **LangGraph**, **Tavily**, **Groq (Llama 3)**, and **FastAPI**. It automates the process of finding, enriching, scoring, and drafting personalized outreach emails for potential leads based on your Ideal Customer Profile (ICP).

## 🌟 Features

- **Automated Search & Enrichment**: Uses Tavily to discover companies matching your target industry and ICP.
- **Intelligent Scoring**: Evaluates each lead using Llama 3 (via Groq) to determine the fit and assigns a score with a detailed reason.
- **Personalized Email Drafting**: Automatically generates highly customized cold outreach emails based on the lead's enriched context.
- **Real-Time Streaming backend**: Built with FastAPI and Server-Sent Events (SSE) to stream the agent's progress in real-time.
- **Interactive UI**: A clean, modern interface to input your targeting criteria and view results dynamically.

## 🛠️ Tech Stack

- **Framework**: [LangGraph](https://python.langchain.com/docs/langgraph)
- **LLM Provider**: [Groq](https://groq.com/) (Llama 3.3 70B)
- **Search API**: [Tavily](https://tavily.com/)
- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) & Uvicorn
- **Frontend**: HTML/JS with Tailwind CSS (or Custom UI)

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- [Groq API Key](https://console.groq.com/keys)
- [Tavily API Key](https://app.tavily.com/home)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/leadflow-ai.git
   cd leadflow-ai
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   Copy `.env.example` to `.env` and add your API keys:
   ```env
   GROQ_API_KEY=your_groq_api_key
   TAVILY_API_KEY=your_tavily_api_key
   ```

### Running the Application

1. Start the FastAPI server:
   ```bash
   python app.py
   ```
   *(or run `uvicorn app:app --host 0.0.0.0 --port 8000 --reload`)*

2. Open your browser and navigate to:
   ```text
   http://localhost:8000
   ```

3. Enter your target industry and ICP, and let the agent do the heavy lifting!

## 📂 Project Structure

- `agent/`: Contains the LangGraph workflow (`graph.py`, `state.py`).
- `tools/`: Individual tool implementations (e.g., search, enrichment, scoring, email writing).
- `app.py`: FastAPI server handling the API endpoints and SSE streaming.
- `static/`: Frontend assets (HTML, CSS, JS).

## 📝 License

This project is licensed under the MIT License.
