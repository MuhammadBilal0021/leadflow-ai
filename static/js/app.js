/* All untrusted content is rendered as text; no dynamic HTML or inline handlers. */
const STAGES = ['search', 'enrich', 'score', 'email'];
function element(tag, className = '', text = '') {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = String(text ?? '');
    return node;
}
function safeUrl(value) {
    if (typeof value !== 'string' || /[\s\\<>"\u0000-\u001f\u007f]/.test(value)) return null;
    try {
        const url = new URL(value);
        if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.port) return null;
        return url.href;
    } catch { return null; }
}
function link(label, value) {
    const href = safeUrl(value);
    if (!href) return element('span', '', label);
    const node = element('a', 'lead-info__url', label);
    node.href = href;
    node.target = '_blank';
    node.rel = 'noopener noreferrer';
    return node;
}

class LeadFlowApp {
    constructor() {
        const ids = {
            form: 'agent-form', btnLaunch: 'btn-launch', pipelineSection: 'pipeline-section',
            resultsSection: 'results-section', configSection: 'config-section',
            logOutput: 'log-output', resultsGrid: 'results-grid', resultsStats: 'results-stats',
            resultsSummary: 'results-summary', btnReset: 'btn-reset', rangeInput: 'num-leads',
            rangeValue: 'num-leads-value', mode: 'run-mode', liveToken: 'live-token',
            history: 'run-history', notice: 'app-notice', metrics: 'run-metrics',
        };
        for (const [key, id] of Object.entries(ids)) this[key] = document.getElementById(id);
        this.btnText = this.btnLaunch.querySelector('.btn-launch__text');
        this.btnIcon = this.btnLaunch.querySelector('.btn-launch__icon');
        this.btnLoader = this.btnLaunch.querySelector('.btn-launch__loader');
        this.currentStageIdx = -1;
        this.form.addEventListener('submit', event => this.handleSubmit(event));
        this.btnReset.addEventListener('click', () => this.reset());
        this.rangeInput.addEventListener('input', () => { this.rangeValue.textContent = this.rangeInput.value; });
        document.getElementById('try-sample').addEventListener('click', () => this.sample());
        document.getElementById('btn-stop').addEventListener('click', () => this.controller?.abort());
        this.mode.addEventListener('change', () => {
            document.getElementById('live-access').hidden = this.mode.value !== 'live';
            this.notice.textContent = this.mode.value === 'sample'
                ? 'Sample mode uses fictional companies and fixed targeting. No API calls.'
                : 'Live research uses your configured providers. Review evidence and all drafts before outreach.';
        });
        this.ready = this.init();
    }

    async init() {
        try {
            const response = await fetch('/api/session');
            if (!response.ok) throw new Error('Could not create a session. Try again later.');
            const session = await response.json();
            document.getElementById('live-option').disabled = !session.live_available;
            this.notice.textContent = session.demo_notice + (session.live_available ? '' : ' Live mode is not configured.');
            await this.loadHistory();
        } catch (error) {
            this.notice.textContent = error.message;
            this.btnLaunch.disabled = true;
        }
    }

    sample() {
        this.mode.value = 'sample';
        this.mode.dispatchEvent(new Event('change'));
        document.getElementById('target-industry').value = 'HR tech SaaS';
        document.getElementById('icp-description').value = 'US-based, 50-200 employees, Series A or B funded';
        document.getElementById('qualification-criteria').value = '';
        this.rangeInput.value = 6;
        this.rangeValue.textContent = '6';
        this.form.requestSubmit();
    }

    async handleSubmit(event) {
        event.preventDefault();
        await this.ready;
        if (this.btnLaunch.disabled) return;
        const data = {
            target_industry: document.getElementById('target-industry').value.trim(),
            icp_description: document.getElementById('icp-description').value.trim(),
            num_leads: Number(this.rangeInput.value),
            sender_context: document.getElementById('sender-context').value.trim() ||
                'I build AI-powered automation tools that reduce manual operations.',
            qualification_criteria: document.getElementById('qualification-criteria').value
                .split('\n').map(value => value.trim()).filter(Boolean),
            demo: this.mode.value === 'sample',
        };
        this.controller = new AbortController();
        this.receivedResult = false;
        this.receivedError = false;
        this.setLoading(true);
        this.showPipeline();
        this.logOutput.replaceChildren();
        this.currentStageIdx = -1;
        let reader;
        try {
            const headers = { 'Content-Type': 'application/json' };
            if (!data.demo) headers.Authorization = 'Bearer ' + this.liveToken.value;
            const response = await fetch('/api/run', {
                method: 'POST', headers, body: JSON.stringify(data), signal: this.controller.signal,
            });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(typeof error.detail === 'string' ? error.detail : 'Invalid input. Check the field limits.');
            }
            if (!response.body) throw new Error('Streaming is unavailable in this browser.');
            reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const chunk = await reader.read();
                buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
                const frames = buffer.split(/\r?\n\r?\n/);
                buffer = frames.pop();
                for (const frame of frames) {
                    const line = frame.split(/\r?\n/).find(value => value.startsWith('data: '));
                    if (line) this.handleEvent(JSON.parse(line.slice(6)));
                }
                if (chunk.done) break;
            }
            if (!this.receivedResult && !this.receivedError) throw new Error('Connection ended before results arrived.');
        } catch (error) {
            this.appendLog(error.name === 'AbortError' ? 'Run cancelled. No further work will be scheduled.' : error.message, 'error');
        } finally {
            reader?.releaseLock();
            this.controller = null;
            this.setLoading(false);
        }
    }

    handleEvent(event) {
        if (event.type === 'stage') {
            this.advanceStage(event.stage);
            this.appendLog('Stage: ' + event.stage, 'stage');
        } else if (event.type === 'result') {
            this.receivedResult = true;
            if (event.data.status !== 'failed') this.completeAllStages();
            this.showResults(event.data);
            this.loadHistory();
        } else if (event.type === 'error') {
            this.receivedError = true;
            this.appendLog(event.message, 'error');
        }
    }

    showPipeline() {
        this.pipelineSection.hidden = false;
        this.resultsSection.hidden = true;
        this.pipelineSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
        document.querySelectorAll('.pipeline-step').forEach(node => node.classList.remove('active', 'completed'));
        document.querySelectorAll('.pipeline-connector').forEach(node => node.classList.remove('filled'));
    }

    advanceStage(stage) {
        const index = STAGES.indexOf(stage);
        if (index < 0 || index <= this.currentStageIdx) return;
        STAGES.forEach((name, i) => {
            const node = document.querySelector('[data-step="' + name + '"]');
            node.classList.toggle('completed', i < index);
            node.classList.toggle('active', i === index);
        });
        document.querySelectorAll('.pipeline-connector').forEach((node, i) => node.classList.toggle('filled', i < index));
        this.currentStageIdx = index;
    }

    completeAllStages() {
        document.querySelectorAll('.pipeline-step').forEach(node => {
            node.classList.remove('active');
            node.classList.add('completed');
        });
        document.querySelectorAll('.pipeline-connector').forEach(node => node.classList.add('filled'));
    }

    appendLog(message, cls = '') {
        this.logOutput.appendChild(element('div', 'log-line log-line--' + cls, '> ' + message));
        this.logOutput.scrollTop = this.logOutput.scrollHeight;
    }

    showResults(data) {
        this.resultsSection.hidden = false;
        this.resultsSummary.textContent = (data.mode === 'sample' ? 'FICTIONAL SAMPLE - ' : '') + data.summary;
        this.resultsGrid.replaceChildren();
        this.resultsStats.replaceChildren();
        const leads = data.leads || [];
        const groups = [
            ['qualified', 'Source-supported matches', 'Review source evidence and drafts before outreach.'],
            ['needs_review', 'Needs review', 'Some evidence is missing, ambiguous, or scoring was unavailable.'],
            ['not_qualified', 'Not qualified', 'At least one requirement has a source-supported contradiction.'],
        ];
        for (const [status, title, description] of groups) {
            const rows = leads.filter(lead => lead.qualification_status === status);
            const stat = element('div', 'stat-card');
            stat.append(element('div', 'stat-value', rows.length), element('div', 'stat-label', title));
            this.resultsStats.appendChild(stat);
            if (!rows.length) continue;
            const section = element('section', 'results-group');
            section.append(element('h3', '', title), element('p', 'lead-info__reason', description));
            for (const lead of rows) section.appendChild(this.createLeadCard(lead));
            this.resultsGrid.appendChild(section);
        }
        if (!leads.length) this.resultsGrid.appendChild(element('p', '', 'No candidates returned. Review the status and warnings.'));
        for (const warning of data.warnings || []) {
            this.resultsGrid.appendChild(element('p', 'info-banner', warning));
        }
        this.resultsGrid.appendChild(element('p', 'info-banner',
            'Source-supported means a quote was found in the retrieved text. It does not independently verify a claim. Drafts are never sent automatically.'));
        const metrics = data.metrics || {};
        const cost = metrics.estimated_cost_usd == null ? 'unavailable (configure provider rates)' : '$' + metrics.estimated_cost_usd.toFixed(6);
        this.metrics.replaceChildren(
            element('p', '', 'Status: ' + data.status + ' | Duration: ' + (metrics.elapsed_seconds ?? '?') + ' s | Estimated cost: ' + cost),
            element('p', '', 'Model calls: ' + (metrics.llm_requests ?? 0) + ' | Search calls: ' + (metrics.search_requests ?? 0) +
                ' | Tokens in/out: ' + (metrics.input_tokens ?? 0) + '/' + (metrics.output_tokens ?? 0)),
        );
        const actions = element('div', 'run-actions');
        const download = element('a', 'btn-reset', 'Export CSV');
        download.href = '/api/runs/' + encodeURIComponent(data.run_id) + '/export';
        download.download = 'leadflow.csv';
        actions.appendChild(download);
        this.metrics.appendChild(actions);
        this.resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    createLeadCard(lead) {
        const card = element('article', 'lead-card ' + (
            lead.qualification_status === 'qualified' ? 'qualified' :
            lead.qualification_status === 'needs_review' ? 'partial' : 'poor'));
        const main = element('div', 'lead-card__main');
        const score = Number.isInteger(lead.score) && lead.score >= 0 && lead.score <= 100 ? lead.score : '?';
        const info = element('div', 'lead-info');
        info.append(element('h3', '', lead.company_name || 'Unknown company'));
        if (lead.website) info.appendChild(link('Company website', lead.website));
        if (lead.profile_url) info.appendChild(link('Company profile (website not resolved)', lead.profile_url));
        info.append(element('p', 'lead-info__reason', lead.score_reason),
            element('p', 'lead-info__reason', 'Scoring: ' + lead.scoring_status + ' | Draft: ' + lead.email_status));
        main.append(element('div', 'score-badge score-badge--partial', score), info);
        card.appendChild(main);
        const evidence = element('details', 'evidence-panel');
        evidence.appendChild(element('summary', '', 'Requirements and source evidence'));
        for (const criterion of lead.criteria || []) {
            evidence.appendChild(element('p', 'criterion', criterion.requirement + ' - ' + criterion.verdict));
            for (const citation of criterion.citations || []) {
                evidence.append(element('blockquote', '', citation.quote),
                    link(citation.kind + ' - ' + citation.retrieved_at, citation.url));
            }
        }
        for (const field of ['industry', 'location', 'employees', 'funding']) {
            const fact = (lead.facts || {})[field];
            evidence.appendChild(element('p', '', field + ': ' + (fact?.value || 'unknown') +
                (fact?.status === 'source_supported' ? ' (source-supported)' : '')));
            if (fact?.citation) evidence.appendChild(link('View ' + field + ' source', fact.citation.url));
        }
        for (const source of lead.sources || []) {
            const detail = element('details', 'source-text');
            detail.append(element('summary', '', source.kind + ' - ' + source.id),
                link('Source | ' + source.retrieved_at, source.url),
                element('p', '', source.text));
            evidence.appendChild(detail);
        }
        card.appendChild(evidence);
        if (lead.email_draft) {
            const section = element('section', 'email-section');
            const header = element('div', 'email-section__header');
            const copy = element('button', 'btn-copy', 'Copy draft');
            copy.type = 'button';
            copy.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(lead.email_draft);
                    copy.textContent = 'Copied';
                    setTimeout(() => { copy.textContent = 'Copy draft'; }, 1500);
                } catch { this.appendLog('Copy unavailable. Select and copy the draft text.', 'error'); }
            });
            header.append(element('span', 'email-section__label', 'Draft - review before sending'), copy);
            section.append(header, element('pre', 'email-section__body', lead.email_draft));
            card.appendChild(section);
        }
        return card;
    }

    async loadHistory() {
        try {
            const response = await fetch('/api/runs');
            if (!response.ok) throw new Error('Saved runs unavailable. Refresh if your session expired.');
            const runs = await response.json();
            this.history.replaceChildren();
            if (!runs.length) this.history.appendChild(element('p', '', 'Your completed runs will appear here for up to 7 days.'));
            for (const run of runs) {
                const row = element('div', 'history-row');
                const open = element('button', 'btn-copy', new Date(run.created_at).toLocaleString() + ' - ' + run.mode + ' - ' + run.status);
                open.type = 'button';
                open.addEventListener('click', async () => {
                    try {
                        const response = await fetch('/api/runs/' + run.run_id);
                        if (!response.ok) throw new Error('This run is no longer available.');
                        this.showResults(await response.json());
                    } catch (error) { this.notice.textContent = error.message; }
                });
                const remove = element('button', 'btn-copy', 'Delete');
                remove.type = 'button';
                remove.addEventListener('click', async () => {
                    const response = await fetch('/api/runs/' + run.run_id, { method: 'DELETE' });
                    if (response.ok) await this.loadHistory();
                    else this.notice.textContent = 'Could not delete this run. Refresh and try again.';
                });
                row.append(open, remove);
                this.history.appendChild(row);
            }
        } catch (error) { this.notice.textContent = error.message; }
    }

    setLoading(loading) {
        this.btnLaunch.disabled = loading;
        document.getElementById('try-sample').disabled = loading;
        document.getElementById('btn-stop').hidden = !loading;
        this.mode.disabled = loading;
        this.btnText.hidden = loading;
        this.btnIcon.hidden = loading;
        this.btnLoader.hidden = !loading;
    }

    reset() {
        this.pipelineSection.hidden = true;
        this.resultsSection.hidden = true;
        this.logOutput.replaceChildren();
        this.currentStageIdx = -1;
        this.configSection.scrollIntoView({ behavior: 'smooth' });
    }
}
if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', () => new LeadFlowApp());
if (typeof module !== 'undefined') module.exports = { safeUrl, LeadFlowApp };
