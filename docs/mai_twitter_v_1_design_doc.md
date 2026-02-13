# MAI.TWITTER – v1 Design Document

## 1. Purpose

Deploy Mai as a semi-autonomous interactive agent on Twitter that:

- Posts prompts
- Monitors replies
- Selectively responds
- Maintains brand-safe tone
- Escalates moderation risks to manual review
- Preserves human cadence through probabilistic decay

Secondary Objectives:

- Increase interactive engagement
- Reinforce builder identity
- Stress test agent routing architecture
- Reuse delay/moderation helpers
- Establish reusable autonomous persona infrastructure

---

## 2. Operational Modes

Config Flag:

mai.twitter.enabled = true | false

Modes:

Auto Mode (default)
- Respond autonomously if moderation safe

Escalation Mode
- If moderation flag triggered → move to Pending Queue

Manual Override Mode
- Operator can approve, edit, deny, or ignore flagged replies

---

## 3. Interaction Loop

1. Mai posts initial prompt
2. System monitors replies via polling
3. For each new reply:
   - Evaluate moderation risk
   - Determine selection probability
   - Apply delay
   - Generate response (if allowed)
   - Log interaction

---

## 4. Moderation Layer

Two-Tier Model

Tier 1 – Lightweight Filter
- Regex / keyword deny list
- Platform spice ceiling
- Basic toxicity filter

If triggered → flag_for_review = true

Tier 2 – Optional LLM Review
- Only used if Tier 1 ambiguous
- Used sparingly to reduce cost

Platform Constraints

If platform == twitter:
- spice_ceiling = configurable (e.g., 4)
- Explicit sexual content blocked
- Inflammatory political content blocked

Escalation Behavior
- Store in pending queue
- Notify operator (log or optional alert)

---

## 5. Selection Logic

Config Values:
- replies_thresh
- random.replies (base probability)
- decay_factor
- max_replies_per_hour

Behavior:

If total_replies ≤ replies_thresh:
- Respond to all safe replies

If total_replies > replies_thresh:
- Respond if random() < base_probability

Reply Decay Model:

effective_probability = base_probability × decay_factor^n

Where:
- n = number of prior replies by Mai in that thread
- decay_factor typically 0.3–0.5

Optional Constraints:
- One reply per user per thread (soft rule)
- Hard cap on total responses per hour

Thread Lock Rule:
If thread_depth > X → sharply reduce probability or halt auto replies

Design Principle:
Short sparks. Not spirals.

---

## 6. Delay Architecture

Reusable Global Delay Helper:

delay = random(min_delay, max_delay)

Example Range:
25–90 seconds

Additional Controls:
- Per-thread cooldown
- Global cooldown between replies

Purpose:
- Avoid deterministic timing
- Reduce bot detection risk
- Simulate human cadence

---

## 7. Context Routing

Internal context object passed to Mai:

{
  platform: "twitter",
  mode: "auto",
  spice_ceiling: 4,
  moderation: "strict",
  thread_depth: n,
  prior_replies: n
}

Mai adjusts tone accordingly.

Twitter Mai is platform-constrained while maintaining identity spine.

---

## 8. Logging & Observability

For each interaction log:
- Reply ID
- User ID
- Flag status
- Probability roll
- Final decision
- Timestamp

Enables:
- Performance tuning
- Probability adjustment
- Postmortem analysis

---

## 9. Kill Switch

Config-based hard stop:

mai.twitter.enabled = false

Immediate stop without redeploy.

---

## 10. Failure States

Potential Issues:
- Rapid reply bursts
- Escalation backlog
- Tone drift
- Quote tweet controversy
- API flagging

Rollback Plan:
1. Disable auto mode
2. Switch to manual drafting mode
3. Revoke API key if necessary
4. Issue clarifying statement if needed

---

## 11. Scarcity Policy

Mai should feel:
- Intentional
- Reactive
- Selective

Not omnipresent.

Respond less. Matter more.

---

## 12. Rollout Strategy – Dual Track Deployment

External Frame (Spectacle Layer)

Mai appears as:
- Mischievous AI persona
- Occasionally awakened
- Selectively engaging
- Not constantly active

Do not reference automation, probabilities, or moderation logic publicly.

Internal Frame (Experiment Layer)

Objectives:
- Measure reply volume
- Measure reply quality
- Identify repeat engagers
- Track tone patterns
- Detect boundary testers

Metrics to log:
- Total replies
- Unique users
- Repeat users
- Response rate
- Escalation rate
- Engagement delta before/after activation
- Thread depth averages

Key Research Questions:
- Do prompts outperform dev updates?
- Do chaotic prompts outperform clever prompts?
- Do certain users consistently engage?
- Does selective response increase follow-up replies?
- Does visible autonomy create curiosity spikes?

---

## 13. Success Criteria (v1 – One Week)

Success is not:
- Viral tweet
- Massive follower spike
- Perfect tone

Success is:
- X% of replies receive engagement from Mai
- At least N unique users interact
- Escalation rate below defined threshold
- No account warnings
- No community discomfort signals

---

## 14. Failure Conditions

Failure is defined as:
- Account warning
- Repeated user discomfort
- Escalation backlog exceeding threshold
- Reply loop malfunction
- Tone drift beyond platform tolerance

All other outcomes are tuning data.

---

## 15. Experiment Window

Duration: One week

At end of window:
- Evaluate metrics
- Adjust probability scaling
- Adjust decay_factor
- Adjust spice_ceiling
- Decide on continuation, expansion, or redesign

This is a controlled experiment and a performative activation layer operating simultaneously.

