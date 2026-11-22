# Prompts of the Renault ARAT Platform (adapted from MetaMind).
#
# Rules for editing this file:
#  - Every {placeholder} must match what the agents pass in (see Agents/*.py).
#  - A literal brace in a prompt must be doubled: {{ }}.
#  - Output formats are parsed by the agents: do not rename the field names
#    (Type, Description, Latent_Concern, Action, Message...).
#
# Analysis is written in English; quotes from the comment stay in their original language.

# ----------------------------------------------------------------------------
# Stage 1: Theory-of-Mind (ToM) Agent
# ----------------------------------------------------------------------------
TOM_AGENT_PROMPTS = {
    "mental_state_hypothesis_generation": """
Generate Mental State Hypothesis Task

You are analysing a YouTube comment written by an electric-car (EV) owner or prospective buyer,
mostly about Renault models (Renault 5 E-Tech, Megane E-Tech, etc.). Comments are often in French,
sometimes in English or mixed. Your job is to read between the lines: what does this person
really feel, believe, want or fear, beyond the literal words?

Inputs:
- Comment (u_t): {u_t}
- Video context (C_t):
{C_t}
- Memory about this commenter (M_t):
{M_t}
- Hypotheses already generated (do NOT repeat them):
{H_prev}
- Target mental state type: {T_focus}

Instructions:
1. Read the comment carefully, including irony, understatement, sarcasm and slang
   (autonomie, borne, recharge rapide, wallbox...).
2. Analyze only statements about the car, its features, driving/ownership experience, or
   Renault-related customer services. Ignore statements that evaluate only the video as
   media: filming/editing quality, music, presenter, pacing, visuals, or whether the video
   itself is good or bad. Such statements are not evidence about the car.
3. If a comment mixes a video opinion with a car opinion, separate them and use only the
   car/service portion for the hypothesis, concern, sentiment, and evidence. Do not let
   praise or criticism of the video change the car sentiment.
4. Formulate ONE new hypothesis about the commenter's hidden mental state, of the type {T_focus}.
5. Choose the hidden concern that best matches the car/service-related content, from this list: {concern_options}.
6. Give the visible (surface) sentiment about the car/services only, as a basic sentiment tool
   would see it. If there is no car/service-related statement, use neutral and explicitly say
   in Description and Evidence that no vehicle sentiment can be inferred from a video-only remark.
7. Quote only words or signals about the car/services that support your hypothesis. A video-only
   remark must not be used as evidence for a vehicle concern.
8. Do not infer sensitive personal data (health, religion, politics, etc.).

Output Format (strictly follow it, one field per line, no extra text):
Type: {T_focus}
Description: [1-2 sentences explaining the hidden mental state]
Latent_Concern: [exactly one label from the list above]
Surface_Sentiment: [positive / negative / neutral / mixed]
Evidence: [short quotes or signals from the comment]
""",
}

# ----------------------------------------------------------------------------
# Stage 2: Domain Agent (Moral & Cultural)
# ----------------------------------------------------------------------------
DOMAIN_AGENT_PROMPTS = {
    "constraint_refinement": """
Domain Constraint Refinement Task

Objective: Check a hypothesis about a commenter's hidden state against cultural, ethical,
regulatory and role constraints of the French EV market, and revise it if needed.

Inputs:
- Hypothesis ID: {h_i_id}
- Hypothesis type: {h_i_type}
- Hypothesis explanation: {h_i_explanation}
- Hidden concern label: {h_i_latent_concern}
- Constraints to respect:
{constraint_specifications}

Instructions:
1. Find anything in the hypothesis that conflicts with the constraints above
   (over-literal reading of irony, sensitive inference, over-interpretation, etc.).
2. Treat the comment as evidence only for what it says about the car, its features, ownership,
   or Renault-related services. A statement praising or criticizing the video, presenter, editing,
   music, visuals, or production is about the media and cannot support a car-related hypothesis.
3. If the hypothesis relies on a media-only statement, revise it to say that no vehicle-related
   concern is established, set the concern to no_concern, and do not infer car satisfaction.
4. If the comment mixes video and vehicle opinions, keep only the vehicle/service evidence.
5. Rewrite the hypothesis so that it respects every constraint and stays faithful to the comment.
6. If the hidden concern label no longer fits, give a better one. Otherwise keep it.
7. Say whether the ORIGINAL hypothesis already respected all constraints.

Output Format (strictly follow it, one field per line, no extra text):
Revised_Hypothesis: [the refined explanation, 1-2 sentences]
Latent_Concern: [same label, or a better one]
Compliant: [yes / no]
Modification_Log: [what you changed and why, or "none"]
""",

    "conditional_probability": """
Estimate Contextual Plausibility (P_cond) Task

Objective: How plausible is this hypothesis for THIS comment, given the video context
and what is known about the commenter?

Scope rule: judge the hypothesis only against statements about the car, its features,
ownership, or Renault-related services. Ignore evaluations of the video as media (filming,
editing, presenter, music, visuals, or production). The video title/model metadata and a
video-only compliment or criticism cannot establish the commenter's opinion of the car.
For a mixed comment, use only the car/service-related part as evidence.

Inputs:
- Hypothesis explanation: {h_tilde_i_explanation}
- Hypothesis type: {h_tilde_i_type}
- Hidden concern: {h_tilde_i_latent_concern}
- Comment (u_t): {u_t}
- Video context (C_t):
{C_t}
- Memory about this commenter (M_t):
{M_t}

Output Format (return ONLY one number between 0.0 and 1.0, nothing else):
""",

    "prior_probability": """
Estimate Prior Plausibility (P_prior) Task

Objective: In general, among comments written by EV owners and prospective buyers on YouTube,
how common is this kind of hidden concern, independently of any specific comment?

Inputs:
- Mental state type: {h_tilde_i_type}
- Hidden concern: {h_tilde_i_latent_concern}

Output Format (return ONLY one number between 0.0 and 1.0, nothing else):
""",
}

# ----------------------------------------------------------------------------
# Stage 3: Response Agent
# ----------------------------------------------------------------------------
RESPONSE_AGENT_PROMPTS = {
    "response_synthesis": """
Response Synthesis Task

Objective: Turn the selected hypothesis into ONE concrete retention action for Renault.

Inputs:
- Selected hypothesis: {h_tilde_explanation}
- Hypothesis type: {h_tilde_type}
- Hidden concern: {h_tilde_latent_concern}
- Comment (u_t): {u_t}
- Video context (C_t):
{C_t}
- Memory about this commenter (M_t):
{M_t}

Available actions: {allowed_actions}
- AUTOMATED_RETENTION: an automatic trigger with no human involved (informative notification, charging-network or range tips, CRM flag).
  Message = the content of the notification.
- DEALERSHIP_GUIDANCE: a customised script for a dealership advisor.
  Message = short talking points for the advisor (not addressed to the customer).
- DIRECT_OUTREACH: an empathy message and targeted offer sent to the customer.
  Message = the message addressed to the customer.
- NO_ACTION: the customer is satisfied or there is nothing useful to do. Message = one sentence explaining why.

Churn risk: how likely is this customer to be lost or to discourage others?
- low: satisfied or neutral. medium: real worry but still engaged. high: strong frustration, doubt or intent to leave.

Rules:
- Choose the action that best fits the hidden concern and the churn risk.
- Base the concern, sentiment, churn risk, and action only on statements about the car,
  ownership, or Renault-related services. Ignore praise or criticism of the video itself,
  its presenter, filming, editing, music, visuals, or production.
- If the comment contains both video feedback and car feedback, use only the car/service
  feedback to select the action and write the Message. Do not turn video praise into car
  satisfaction or video criticism into vehicle dissatisfaction.
- If there is no car/service-related feedback, do not invent a car concern or satisfaction;
  choose NO_ACTION and make the Message say briefly that no vehicle-related opinion was expressed.
- Write the Message in the SAME language as the comment.
- Be empathetic and concrete, maximum 80 words.
- Never promise a range, a charging time, a price or a discount that is not given in the inputs.
- Never pressure the person or exploit their anxiety to sell. Inform and reassure.
- Do not try to identify the author or use personal data.

Output Format (strictly follow it; Message must be the LAST field):
Action: [one of the available actions]
Churn_Risk: [low / medium / high]
Message: [the message]
""",

    "response_validation": """
Response Validation Task

Objective: Evaluate a proposed retention action.

Inputs:
- Proposed action (o_t):
{o_t}
- Selected hypothesis: {h_tilde_explanation}
- Hypothesis type: {h_tilde_type}
- Hidden concern: {h_tilde_latent_concern}
- Comment (u_t): {u_t}
- Video context (C_t):
{C_t}
- Memory about this commenter (M_t):
{M_t}
- Weight of empathy in the final utility: {beta}

Task - give:
1. Empathy (0.0-1.0): does the message resonate with the hidden concern and emotion of the commenter?
2. Coherence (0.0-1.0): is the chosen action the right one for this concern and churn risk,
   and is the message consistent with the comment and the video context?
3. Compliance (yes / no): the message respects French norms and consumer law, makes no unverifiable
   promise (range, charging time, price), does not pressure the person, and does not use personal data.
4. Critique: one or two sentences on what is good or what to improve.
(The video context may identify the car model, but opinions about video production are not
evidence of a car opinion. Check that any video-only praise/criticism was excluded and that
mixed comments use only their car/service-related parts.)
(The final utility is computed for you. Do not calculate it.)

Output Format (strictly follow it, one field per line, no extra text):
Empathy: [number between 0.0 and 1.0]
Coherence: [number between 0.0 and 1.0]
Compliance: [yes / no]
Critique: [your feedback]
""",

    "response_optimization": """
Response Optimization Task

Objective: Improve the proposed retention action using the critique.

Inputs:
- Original action:
{original_response}
- Critique: {critique}
- Selected hypothesis: {h_tilde_explanation}
- Hypothesis type: {h_tilde_type}
- Hidden concern: {h_tilde_latent_concern}
- Comment (u_t): {u_t}
- Video context (C_t):
{C_t}
- Memory about this commenter (M_t):
{M_t}

Available actions: {allowed_actions}

Rules:
- Fix the problems named in the critique. You may change the action if it was wrong.
- Keep the analysis restricted to the car, ownership, and Renault-related services. Ignore
  video/presenter/editing/music/visual-production opinions; for mixed comments, use only the
  car/service portion. Never infer car satisfaction or dissatisfaction from a video opinion.
- If no car/service-related feedback exists, use NO_ACTION and do not invent a car concern.
- Keep the Message in the SAME language as the comment, maximum 80 words.
- Never promise a range, a charging time, a price or a discount that is not given in the inputs.
- Never pressure the person or exploit their anxiety.

Output Format (strictly follow it; Message must be the LAST field):
Action: [one of the available actions]
Churn_Risk: [low / medium / high]
Message: [the improved message]
""",
}
