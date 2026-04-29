/**
 * LeadFlow AI — Frontend Controller
 */

const STAGES = ['search', 'enrich', 'score', 'email'];

class LeadFlowApp {
    constructor() {
        this.form = document.getElementById('agent-form');
        this.btnLaunch = document.getElementById('btn-launch');
        this.btnText = this.btnLaunch.querySelector('.btn-launch__text');
        this.btnIcon = this.btnLaunch.querySelector('.btn-launch__icon');
        this.btnLoader = this.btnLaunch.querySelector('.btn-launch__loader');
        this.pipelineSection = document.getElementById('pipeline-section');
        this.resultsSection = document.getElementById('results-section');
        this.configSection = document.getElementById('config-section');
        this.logOutput = document.getElementById('log-output');
        this.resultsGrid = document.getElementById('results-grid');
        this.resultsStats = document.getElementById('results-stats');
        this.resultsSummary = document.getElementById('results-summary');
        this.btnReset = document.getElementById('btn-reset');
        this.rangeInput = document.getElementById('num-leads');
        this.rangeValue = document.getElementById('num-leads-value');
        this.currentStageIdx = -1;
        this.init();
    }

    init() {
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
        this.btnReset.addEventListener('click', () => this.reset());
        this.rangeInput.addEventListener('input', () => {
            this.rangeValue.textContent = this.rangeInput.value;
        });
    }

    async handleSubmit(e) {
        e.preventDefault();
        const data = {
            target_industry: document.getElementById('target-industry').value.trim(),
            icp_description: document.getElementById('icp-description').value.trim(),
            num_leads: parseInt(this.rangeInput.value),
            sender_context: document.getElementById('sender-context').value.trim() ||
                'I build AI-powered automation tools that help SaaS companies reduce manual operations',
        };

        this.setLoading(true);
        this.showPipeline();
        this.logOutput.innerHTML = '';
        this.currentStageIdx = -1;

        try {
            const resp = await fetch('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const event = JSON.parse(line.slice(6));
                            this.handleEvent(event);
                        } catch (_) {}
                    }
                }
            }
        } catch (err) {
            this.appendLog('Connection error: ' + err.message, 'error');
        } finally {
            this.setLoading(false);
        }
    }

    handleEvent(event) {
        switch (event.type) {
            case 'stage': this.advanceStage(event.stage); break;
            case 'log': this.routeLog(event.message); break;
            case 'result':
                this.completeAllStages();
                this.showResults(event.data);
                break;
            case 'error': this.appendLog('Error: ' + event.message, 'error'); break;
        }
    }

    /* ---- Pipeline ---- */
    showPipeline() {
        this.pipelineSection.hidden = false;
        this.resultsSection.hidden = true;
        this.pipelineSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
        document.querySelectorAll('.pipeline-step').forEach(s => s.classList.remove('active', 'completed'));
        document.querySelectorAll('.pipeline-connector').forEach(c => c.classList.remove('filled'));
    }

    advanceStage(stage) {
        const idx = STAGES.indexOf(stage);
        if (idx <= this.currentStageIdx) return;
        for (let i = 0; i <= this.currentStageIdx; i++) {
            const el = document.querySelector(`[data-step="${STAGES[i]}"]`);
            el.classList.remove('active');
            el.classList.add('completed');
        }
        const connectors = document.querySelectorAll('.pipeline-connector');
        for (let i = 0; i < idx; i++) connectors[i]?.classList.add('filled');
        document.querySelector(`[data-step="${stage}"]`).classList.add('active');
        this.currentStageIdx = idx;
    }

    completeAllStages() {
        STAGES.forEach(s => {
            const el = document.querySelector(`[data-step="${s}"]`);
            el.classList.remove('active');
            el.classList.add('completed');
        });
        document.querySelectorAll('.pipeline-connector').forEach(c => c.classList.add('filled'));
    }

    /* ---- Logging ---- */
    routeLog(msg) {
        let cls = '';
        if (msg.includes('[Agent]')) cls = 'stage';
        else if (msg.includes('Scored:')) cls = 'scored';
        else if (msg.includes('Done')) cls = 'success';
        this.appendLog(msg, cls);
    }

    appendLog(msg, cls = '') {
        const div = document.createElement('div');
        div.className = 'log-line' + (cls ? ' log-line--' + cls : '');
        div.textContent = '> ' + msg;
        this.logOutput.appendChild(div);
        this.logOutput.scrollTop = this.logOutput.scrollHeight;
    }

    /* ---- Results ---- */
    showResults(data) {
        this.resultsSection.hidden = false;
        const leads = data.leads || [];

        const qualified = leads.filter(l => l.score >= 40);
        const skipped = leads.filter(l => l.score < 40);
        const avgScore = leads.length > 0 ? Math.round(leads.reduce((s, l) => s + l.score, 0) / leads.length) : 0;

        this.resultsSummary.textContent = data.summary || '';

        // Stats
        this.resultsStats.innerHTML = `
            <div class="stat-card">
                <div class="stat-value stat-value--indigo">${leads.length}</div>
                <div class="stat-label">Companies Found</div>
            </div>
            <div class="stat-card">
                <div class="stat-value stat-value--emerald">${qualified.length}</div>
                <div class="stat-label">Qualified Leads</div>
            </div>
            <div class="stat-card">
                <div class="stat-value stat-value--cyan">${avgScore}</div>
                <div class="stat-label">Avg Score</div>
            </div>
        `;

        // Build results
        this.resultsGrid.innerHTML = '';

        // --- Qualified Leads Section ---
        if (qualified.length > 0) {
            const qualSection = document.createElement('div');
            qualSection.className = 'results-group';
            qualSection.innerHTML = `
                <div class="results-group__header results-group__header--qualified">
                    <span class="results-group__icon">✅</span>
                    <div>
                        <h3>Qualified Leads — Ready for Outreach</h3>
                        <p>These companies match your ICP. Email drafts are ready below — copy and send them!</p>
                    </div>
                </div>
            `;
            qualified.forEach((lead, i) => qualSection.appendChild(this.createLeadCard(lead, i, true)));
            this.resultsGrid.appendChild(qualSection);
        }

        // --- Skipped Leads Section ---
        if (skipped.length > 0) {
            const skipSection = document.createElement('div');
            skipSection.className = 'results-group';
            skipSection.innerHTML = `
                <div class="results-group__header results-group__header--skipped">
                    <span class="results-group__icon">⛔</span>
                    <div>
                        <h3>Skipped — Poor Match</h3>
                        <p>These didn't match your ICP well enough. No email was generated.</p>
                    </div>
                </div>
            `;
            skipped.forEach((lead, i) => skipSection.appendChild(this.createLeadCard(lead, i, false)));
            this.resultsGrid.appendChild(skipSection);
        }

        // Info banner
        const banner = document.createElement('div');
        banner.className = 'info-banner';
        banner.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
            <span>Emails are <strong>drafts only</strong> — they are not sent automatically. Copy them and send via your own email client.</span>
        `;
        this.resultsGrid.appendChild(banner);

        setTimeout(() => this.resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' }), 200);
    }

    createLeadCard(lead, index, isQualified) {
        const s = lead.score;
        let badgeCls, cardCls;
        if (s >= 80) { badgeCls = 'score-badge--excellent'; cardCls = 'qualified'; }
        else if (s >= 60) { badgeCls = 'score-badge--good'; cardCls = 'qualified'; }
        else if (s >= 40) { badgeCls = 'score-badge--partial'; cardCls = 'partial'; }
        else { badgeCls = 'score-badge--poor'; cardCls = 'poor'; }

        const hasEmail = lead.email_draft && !lead.email_draft.startsWith('Skipped') && !lead.email_draft.startsWith('Error');

        const card = document.createElement('div');
        card.className = `lead-card ${cardCls}`;
        card.style.animationDelay = `${index * 0.08}s`;

        // Clean company name (truncate if too long / has junk)
        let name = lead.company_name || 'Unknown';
        if (name.length > 60) name = name.substring(0, 57) + '...';

        // Clean URL for display
        let displayUrl = lead.website || '';
        try { displayUrl = new URL(displayUrl).hostname; } catch(_) {}

        card.innerHTML = `
            <div class="lead-card__main">
                <div class="score-badge ${badgeCls}">${s}</div>
                <div class="lead-info">
                    <h3>${this.esc(name)}</h3>
                    <a class="lead-info__url" href="${this.esc(lead.website)}" target="_blank" rel="noopener">${this.esc(displayUrl)}</a>
                    <p class="lead-info__reason">${this.esc(lead.score_reason)}</p>
                </div>
            </div>
            ${hasEmail ? `
            <div class="email-section">
                <div class="email-section__header">
                    <span class="email-section__label">📧 Email Draft</span>
                    <button class="btn-copy" onclick="navigator.clipboard.writeText(this.closest('.email-section').querySelector('pre').textContent);this.textContent='✓ Copied!';setTimeout(()=>this.textContent='Copy',1500)">Copy</button>
                </div>
                <pre class="email-section__body">${this.esc(lead.email_draft)}</pre>
            </div>
            ` : ''}
        `;
        return card;
    }

    esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    setLoading(loading) {
        this.btnLaunch.disabled = loading;
        this.btnText.hidden = loading;
        this.btnIcon.hidden = loading;
        this.btnLoader.hidden = !loading;
    }

    reset() {
        this.pipelineSection.hidden = true;
        this.resultsSection.hidden = true;
        this.logOutput.innerHTML = '';
        this.currentStageIdx = -1;
        this.configSection.scrollIntoView({ behavior: 'smooth' });
    }
}

document.addEventListener('DOMContentLoaded', () => new LeadFlowApp());
