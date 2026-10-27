const test = require('node:test');
const assert = require('node:assert/strict');
const { safeUrl, LeadFlowApp } = require('../static/js/app.js');

class Node {
    constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.children.push(child); return child; }
    addEventListener() {}
    set innerHTML(value) { throw new Error('Unsafe HTML sink used'); }
}
global.document = { createElement: tag => new Node(tag) };
function all(node) { return [node, ...node.children.flatMap(all)]; }

test('unsafe URL protocols, credentials and attribute injection are rejected', () => {
    for (const url of ['javascript:alert(1)', 'data:text/html,x', 'https://u:p@example.com',
        'https://example.com/" onmouseover="alert(1)', 'https://example.com/\n', 'https://example.com:8443']) {
        assert.equal(safeUrl(url), null);
    }
    assert.equal(safeUrl('https://example.com/about'), 'https://example.com/about');
});

test('untrusted company, quote, reason and email remain text without HTML sinks', () => {
    const payload = '<img src=x onerror=alert(1)>';
    const lead = { company_name: payload, website: 'javascript:alert(1)', score: 999,
        score_reason: payload, email_draft: payload, qualification_status: 'qualified',
        scoring_status: 'complete', email_status: 'draft_needs_review',
        criteria: [{requirement: payload, verdict: 'match',
            citations: [{quote: payload, url: 'javascript:alert(1)', kind: 'search', retrieved_at: 'today'}]}],
        sources: [{id:'s0', text:payload, url:'javascript:alert(1)', kind:'search'}] };
    const card = LeadFlowApp.prototype.createLeadCard.call({}, lead);
    const nodes = all(card);
    assert(nodes.some(node => node.textContent === payload));
    assert(!nodes.some(node => node.href?.startsWith('javascript:')));
    assert(nodes.some(node => node.textContent === '?'));
    assert(!nodes.some(node => node.tag === 'img'));
});
