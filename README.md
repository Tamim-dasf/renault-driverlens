# DriverLens Platform

> A 3-agent AI system that finds the hidden concern behind YouTube comments about Renault electric cars and suggests a marketing action.

**Aix-Marseille Université** | Academic project (Marketing)

## 📖 Overview

DriverLens analyzes public YouTube comments about the Renault 5, Renault 4, Mégane and Scénic E-Tech. A basic sentiment tool reads *"Super voiture, mais je ne sais pas si elle tiendra l'hiver"* as positive. DriverLens detects a hidden **range anxiety**, estimates the **churn risk**, and proposes a reassuring message.

It is a proof of concept, adapted from the [MetaMind](https://github.com/XMZhangAI/MetaMind) multi-agent framework.

## ⚙️ How it works

| Agent | Role |
|---|---|
| **1. Theory of Mind** | Generates hypotheses about the hidden feeling behind the comment, plus a "nothing is hidden" candidate. |
| **2. Domain expert** | Checks them against French market rules (irony, GDPR, no pressure selling) and selects the most plausible one with a score. |
| **3. Response** | Chooses an action (automated message, dealership script, direct outreach or no action), rates the churn risk, then drafts and validates the message. |

## 🧪 Study design

- Comments are split once, **60% / 40%**.
- **60%:** analyzed in daily batches (20 per run). Each result feeds a shared **memory** used as context and as prior probabilities. Nothing is trained.
- **40%:** held-out test comments, analyzed **with** and **without** the memory.
- A person labels the test comments by hand, and `evaluate.py` compares the labels with the agents' answers.
- A local dashboard shows the results.

## 🚀 Run it

1. Clone and install: `git clone https://github.com/Tamim-dasf/renault-driverlens.git`, then `pip install -r requirements.txt`
2. Create a `.env` file containing `GEMINI_API_KEY=your_key` and `GEMINI_MODEL=model_id` (never commit it)
3. Put your comment exports (`.csv` or `.xlsx`) in the `our data` folder
4. Preview without a key: `python main.py --phase train --dry-run`
5. Real batch of comments: `python main.py --phase train`
6. Dashboard: `python app.py`, then open http://127.0.0.1:5000
7. Evaluation: `python evaluate.py make-sheet --n 30`, label the sheet in Excel, run `python main.py --phase test --n 30` and again with `--no-memory`, then `python evaluate.py score`

## 🚧 Limitations

- Proof of concept on a sample of comments, because of free API limits.
- The memory is built from the system's own answers: it is not model training and can repeat its mistakes.
- With few labeled comments, the metrics are indicative, not conclusive.

## 🔒 Privacy

Only public comments are used. @mentions are removed and no author name is stored.

## 🙏 Credits and authors

MetaMind: Zhang, X. et al. (2025). Language model: Google Gemini.

Authors: [Your Name 1], [Your Name 2]

