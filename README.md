# DriverLens Platform
> Marketing project analyzing Renault EV YouTube comments using a 3-agent AI system.

**Aix-Marseille Université** | Academic Project

## 📖 Overview
DriverLens is an AI application designed to uncover hidden customer concerns from YouTube comments about Renault electric vehicles (Renault 5, 4, Mégane, Scénic E-Tech). Instead of simple sentiment analysis, it uses a 3-agent AI pipeline to read between the lines, estimate churn risk, and suggest marketing actions.

## ⚙️ How it Works
1. **Data Pipeline:** Collects and cleans comments, splitting them into 60% training and 40% testing.
2. **Agent 1 (Theory of Mind):** Guesses the hidden mental state (Belief, Desire, Emotion, etc.) behind the comment.
3. **Agent 2 (Domain Expert):** Checks the hypotheses against French market rules and selects the most plausible one using a mathematical score.
4. **Agent 3 (Response):** Drafts a marketing response (or action) and evaluates its own Empathy and Coherence before finalizing.

## 🚀 How to Run Locally
1. Clone the repository:
   ```bash
   git clone https://github.com/Tamim-dasf/renault-driverlens.git

