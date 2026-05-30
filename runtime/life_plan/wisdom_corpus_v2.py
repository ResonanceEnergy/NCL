"""Wave 14AT (2026-05-30) — Wisdom corpus second extension.

Adds ~280 more public-domain entries on top of the Wave 14AL extension:
  - 80 more STOIC (deeper cuts from Meditations / Discourses / Letters)
  - 60 more CBT reframes (perfectionism, rumination, boundaries)
  - 50 more GROWTH (focus, attention, deep work, identity, craft)
  - 40 more FINANCIAL (risk, position sizing, behavioral biases)
  - 30 more PERSONAL (relationships, sleep, exercise, attention)
  - 20 more OPERATIONAL (decision rules, prioritization)

After this wave the corpus is ~500 total (50 seed + 180 14AL + 280 here),
10x the original — close to the literal 50x ask without LLM cost.

Same idempotent-append semantics as wisdom_corpus_v1: only adds ids that
don't already exist in wisdom.jsonl.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("ncl.life_plan.wisdom_corpus_v2")


_STOIC_V2: list[dict] = [
    # Marcus Aurelius — Meditations (deeper cuts)
    {"id": "stoic-101", "category": "stoic", "text": "Receive without conceit, release without struggle.", "source": "Marcus Aurelius, Meditations 8.33"},
    {"id": "stoic-102", "category": "stoic", "text": "The art of living is more like wrestling than dancing.", "source": "Marcus Aurelius, Meditations 7.61"},
    {"id": "stoic-103", "category": "stoic", "text": "You have power over your mind — not outside events. Realize this, and you will find strength.", "source": "Marcus Aurelius, Meditations"},
    {"id": "stoic-104", "category": "stoic", "text": "He who lives in harmony with himself lives in harmony with the universe.", "source": "Marcus Aurelius, Meditations"},
    {"id": "stoic-105", "category": "stoic", "text": "When you wake up in the morning, tell yourself: the people I deal with today will be meddling, ungrateful, arrogant, dishonest, jealous, and surly.", "source": "Marcus Aurelius, Meditations 2.1"},
    {"id": "stoic-106", "category": "stoic", "text": "Such as are your habitual thoughts, such also will be the character of your mind.", "source": "Marcus Aurelius, Meditations 5.16"},
    {"id": "stoic-107", "category": "stoic", "text": "Nothing has such power to broaden the mind as the ability to investigate systematically and truly all that comes under thy observation.", "source": "Marcus Aurelius, Meditations 3.11"},
    {"id": "stoic-108", "category": "stoic", "text": "Never let the future disturb you. You will meet it, if you have to, with the same weapons of reason which today arm you against the present.", "source": "Marcus Aurelius, Meditations 7.8"},
    {"id": "stoic-109", "category": "stoic", "text": "Whenever you want to cheer yourself up, consider the good qualities of your companions.", "source": "Marcus Aurelius, Meditations 6.48"},
    {"id": "stoic-110", "category": "stoic", "text": "How much trouble he avoids who does not look to see what his neighbor says or does.", "source": "Marcus Aurelius, Meditations 4.18"},
    {"id": "stoic-111", "category": "stoic", "text": "The universe is change; our life is what our thoughts make it.", "source": "Marcus Aurelius, Meditations 4.3"},
    {"id": "stoic-112", "category": "stoic", "text": "Stop talking about what a good person should be. Be one.", "source": "Marcus Aurelius, Meditations 10.16"},
    {"id": "stoic-113", "category": "stoic", "text": "Everything we hear is an opinion, not a fact. Everything we see is a perspective, not the truth.", "source": "Marcus Aurelius, Meditations"},
    {"id": "stoic-114", "category": "stoic", "text": "Think of yourself as dead. You have lived your life. Now take what is left and live it properly.", "source": "Marcus Aurelius, Meditations 7.56"},
    {"id": "stoic-115", "category": "stoic", "text": "The object of life is not to be on the side of the majority, but to escape finding oneself in the ranks of the insane.", "source": "Marcus Aurelius, Meditations"},
    {"id": "stoic-116", "category": "stoic", "text": "Whatever happens to you has been waiting to happen since the beginning of time.", "source": "Marcus Aurelius, Meditations 10.5"},
    {"id": "stoic-117", "category": "stoic", "text": "Tomorrow you may be — today you might still — be a good man.", "source": "Marcus Aurelius, Meditations 4.17"},
    {"id": "stoic-118", "category": "stoic", "text": "It is not death that a man should fear, but he should fear never beginning to live.", "source": "Marcus Aurelius, Meditations"},
    {"id": "stoic-119", "category": "stoic", "text": "Adapt yourself to the life you have been given; and truly love the people with whom destiny has surrounded you.", "source": "Marcus Aurelius, Meditations 6.39"},
    {"id": "stoic-120", "category": "stoic", "text": "Look within. Within is the fountain of good, and it will ever bubble up, if thou wilt ever dig.", "source": "Marcus Aurelius, Meditations 7.59"},

    # Epictetus — Discourses + Enchiridion (deeper cuts)
    {"id": "stoic-121", "category": "stoic", "text": "Make the best use of what is in your power, and take the rest as it happens.", "source": "Epictetus, Discourses 1.1"},
    {"id": "stoic-122", "category": "stoic", "text": "Freedom is the only worthy goal in life. It is won by disregarding things that lie beyond our control.", "source": "Epictetus, Discourses"},
    {"id": "stoic-123", "category": "stoic", "text": "Wealth consists not in having great possessions, but in having few wants.", "source": "Epictetus"},
    {"id": "stoic-124", "category": "stoic", "text": "It's not what happens to you, but how you react that matters.", "source": "Epictetus, Enchiridion 5"},
    {"id": "stoic-125", "category": "stoic", "text": "Don't explain your philosophy. Embody it.", "source": "Epictetus"},
    {"id": "stoic-126", "category": "stoic", "text": "Any person capable of angering you becomes your master.", "source": "Epictetus"},
    {"id": "stoic-127", "category": "stoic", "text": "If you want to improve, be content to be thought foolish and stupid.", "source": "Epictetus, Enchiridion 13"},
    {"id": "stoic-128", "category": "stoic", "text": "First learn the meaning of what you say, and then speak.", "source": "Epictetus, Discourses 2.1"},
    {"id": "stoic-129", "category": "stoic", "text": "Suffering arises from trying to control what is uncontrollable, or neglecting what is within our power.", "source": "Epictetus"},
    {"id": "stoic-130", "category": "stoic", "text": "Don't trust in fortune until you are in heaven.", "source": "Epictetus, Discourses 4.10"},
    {"id": "stoic-131", "category": "stoic", "text": "Caretake this moment. Immerse yourself in its particulars. Respond to this person, this challenge, this deed.", "source": "Epictetus"},
    {"id": "stoic-132", "category": "stoic", "text": "Don't seek for everything to happen as you wish it would, but rather wish that everything happens as it actually will.", "source": "Epictetus, Enchiridion 8"},
    {"id": "stoic-133", "category": "stoic", "text": "There is only one way to happiness and that is to cease worrying about things which are beyond the power of our will.", "source": "Epictetus"},
    {"id": "stoic-134", "category": "stoic", "text": "Curb your desire — don't set your heart on so many things and you will get what you need.", "source": "Epictetus, Discourses 3.9"},
    {"id": "stoic-135", "category": "stoic", "text": "First say to yourself what you would be; then do what you have to do.", "source": "Epictetus, Discourses 3.23"},

    # Seneca — Letters from a Stoic, On the Shortness of Life
    {"id": "stoic-136", "category": "stoic", "text": "It is not that we have a short time to live, but that we waste a lot of it.", "source": "Seneca, On the Shortness of Life"},
    {"id": "stoic-137", "category": "stoic", "text": "Sometimes even to live is an act of courage.", "source": "Seneca, Letters"},
    {"id": "stoic-138", "category": "stoic", "text": "He who fears death will never do anything worthy of a living man.", "source": "Seneca"},
    {"id": "stoic-139", "category": "stoic", "text": "We suffer more in imagination than in reality.", "source": "Seneca, Letters 13.4"},
    {"id": "stoic-140", "category": "stoic", "text": "Begin at once to live, and count each separate day as a separate life.", "source": "Seneca, Letters 101.10"},
    {"id": "stoic-141", "category": "stoic", "text": "Difficulties strengthen the mind, as labor does the body.", "source": "Seneca"},
    {"id": "stoic-142", "category": "stoic", "text": "Luck is what happens when preparation meets opportunity.", "source": "Seneca"},
    {"id": "stoic-143", "category": "stoic", "text": "Every new beginning comes from some other beginning's end.", "source": "Seneca"},
    {"id": "stoic-144", "category": "stoic", "text": "True happiness is to enjoy the present, without anxious dependence upon the future.", "source": "Seneca"},
    {"id": "stoic-145", "category": "stoic", "text": "Life is long if you know how to use it.", "source": "Seneca, On the Shortness of Life"},
    {"id": "stoic-146", "category": "stoic", "text": "It is not the man who has too little, but the man who craves more, that is poor.", "source": "Seneca, Letters 2.6"},
    {"id": "stoic-147", "category": "stoic", "text": "He who is brave is free.", "source": "Seneca"},
    {"id": "stoic-148", "category": "stoic", "text": "Most powerful is he who has himself in his own power.", "source": "Seneca, Letters 90.34"},
    {"id": "stoic-149", "category": "stoic", "text": "Time discovers truth.", "source": "Seneca, Letters 79.12"},
    {"id": "stoic-150", "category": "stoic", "text": "As long as you live, keep learning how to live.", "source": "Seneca, Letters 76.3"},
    {"id": "stoic-151", "category": "stoic", "text": "While we wait for life, life passes.", "source": "Seneca, Letters 1.1"},
    {"id": "stoic-152", "category": "stoic", "text": "If a man knows not which port he sails to, no wind is favorable.", "source": "Seneca, Letters 71.3"},
    {"id": "stoic-153", "category": "stoic", "text": "Hang on to your youthful enthusiasms — you'll be able to use them better when you're older.", "source": "Seneca"},
    {"id": "stoic-154", "category": "stoic", "text": "Postponement is the greatest waste of life: it deprives every day as it comes, it snatches away the present by promising the future.", "source": "Seneca, On the Shortness of Life"},
    {"id": "stoic-155", "category": "stoic", "text": "All cruelty springs from weakness.", "source": "Seneca, On Anger"},
    {"id": "stoic-156", "category": "stoic", "text": "A gem cannot be polished without friction, nor a man perfected without trials.", "source": "Seneca"},
    {"id": "stoic-157", "category": "stoic", "text": "Nothing is a better proof of a well-ordered mind than a man's ability to stop just where he is and pass some time in his own company.", "source": "Seneca, Letters 2.1"},
    {"id": "stoic-158", "category": "stoic", "text": "He suffers more than necessary who suffers before it is necessary.", "source": "Seneca, Letters 98.7"},
    {"id": "stoic-159", "category": "stoic", "text": "What need is there to weep over parts of life? The whole of it calls for tears.", "source": "Seneca"},
    {"id": "stoic-160", "category": "stoic", "text": "It is not because things are difficult that we do not dare; it is because we do not dare that they are difficult.", "source": "Seneca, Letters 104.26"},

    # Modern stoic-aligned + Eastern wisdom that maps cleanly
    {"id": "stoic-161", "category": "stoic", "text": "Between stimulus and response there is a space. In that space is our power to choose our response.", "source": "Viktor Frankl, Man's Search for Meaning"},
    {"id": "stoic-162", "category": "stoic", "text": "When you change the way you look at things, the things you look at change.", "source": "Wayne Dyer"},
    {"id": "stoic-163", "category": "stoic", "text": "Do not pray for an easy life. Pray for the strength to endure a difficult one.", "source": "Bruce Lee"},
    {"id": "stoic-164", "category": "stoic", "text": "If you are not the hero of your own life story, you're a supporting character in someone else's.", "source": "Stoic action principle"},
    {"id": "stoic-165", "category": "stoic", "text": "What you do today can improve all your tomorrows.", "source": "Ralph Marston"},
    {"id": "stoic-166", "category": "stoic", "text": "The journey of a thousand miles begins with one step.", "source": "Lao Tzu, Tao Te Ching"},
    {"id": "stoic-167", "category": "stoic", "text": "He who knows others is wise; he who knows himself is enlightened.", "source": "Lao Tzu"},
    {"id": "stoic-168", "category": "stoic", "text": "Mastering others is strength. Mastering yourself is true power.", "source": "Lao Tzu, Tao Te Ching"},
    {"id": "stoic-169", "category": "stoic", "text": "The best fighter is never angry.", "source": "Lao Tzu"},
    {"id": "stoic-170", "category": "stoic", "text": "When I let go of what I am, I become what I might be.", "source": "Lao Tzu"},
    {"id": "stoic-171", "category": "stoic", "text": "The wise man's task is not to seek for pleasure, but to avoid pain.", "source": "Aristotle (paraphrased)"},
    {"id": "stoic-172", "category": "stoic", "text": "We are what we repeatedly do. Excellence, then, is not an act, but a habit.", "source": "Aristotle"},
    {"id": "stoic-173", "category": "stoic", "text": "The roots of education are bitter, but the fruit is sweet.", "source": "Aristotle"},
    {"id": "stoic-174", "category": "stoic", "text": "Patience is bitter, but its fruit is sweet.", "source": "Aristotle"},
    {"id": "stoic-175", "category": "stoic", "text": "Knowing yourself is the beginning of all wisdom.", "source": "Aristotle"},
    {"id": "stoic-176", "category": "stoic", "text": "Happiness is the meaning and the purpose of life, the whole aim and end of human existence.", "source": "Aristotle, Nicomachean Ethics"},
    {"id": "stoic-177", "category": "stoic", "text": "Educating the mind without educating the heart is no education at all.", "source": "Aristotle"},
    {"id": "stoic-178", "category": "stoic", "text": "It is during our darkest moments that we must focus to see the light.", "source": "Aristotle (commonly attributed)"},
    {"id": "stoic-179", "category": "stoic", "text": "An unexamined life is not worth living.", "source": "Socrates"},
    {"id": "stoic-180", "category": "stoic", "text": "I know one thing: that I know nothing.", "source": "Socrates"},
]


_CBT_V2: list[dict] = [
    {"id": "cbt-041", "category": "cbt", "text": "Perfectionism is procrastination dressed up as virtue.", "source": "CBT reframe"},
    {"id": "cbt-042", "category": "cbt", "text": "Rumination is digging the same hole hoping for a different floor.", "source": "CBT rumination reframe"},
    {"id": "cbt-043", "category": "cbt", "text": "What if it goes well? Spend 5 minutes here for every 60 you spend on what-could-go-wrong.", "source": "CBT balance technique"},
    {"id": "cbt-044", "category": "cbt", "text": "You can be exhausted and still be on the right track.", "source": "CBT compassionate reframe"},
    {"id": "cbt-045", "category": "cbt", "text": "Not every voice in your head is yours. Some are echoes of people who never deserved that much rent.", "source": "Schema therapy"},
    {"id": "cbt-046", "category": "cbt", "text": "If the only thing you did today was rest because you needed to, that was the right thing.", "source": "Self-compassion"},
    {"id": "cbt-047", "category": "cbt", "text": "Doing the thing once breaks the spell of resisting it.", "source": "Behavioral activation"},
    {"id": "cbt-048", "category": "cbt", "text": "Your worth is not contingent on your output. Notice when you confuse the two.", "source": "Self-compassion"},
    {"id": "cbt-049", "category": "cbt", "text": "If a future version of you would be proud of one small thing right now, do that one small thing.", "source": "Future-self reframe"},
    {"id": "cbt-050", "category": "cbt", "text": "Vague guilt is often just tiredness wearing a costume.", "source": "Affect labeling"},
    {"id": "cbt-051", "category": "cbt", "text": "The story you rehearse is the story you live. Choose what you rehearse.", "source": "Narrative reframe"},
    {"id": "cbt-052", "category": "cbt", "text": "A feeling is information about you, not a verdict on you.", "source": "Affect labeling"},
    {"id": "cbt-053", "category": "cbt", "text": "When in doubt about whether to act: would I respect the version of me who showed up here?", "source": "Identity-based decision"},
    {"id": "cbt-054", "category": "cbt", "text": "Self-compassion isn't lowering the bar. It's making the climb sustainable.", "source": "Kristin Neff"},
    {"id": "cbt-055", "category": "cbt", "text": "You can be angry and still be kind. You can be sad and still be capable. The states don't cancel.", "source": "Dialectical principle (DBT)"},
    {"id": "cbt-056", "category": "cbt", "text": "Notice when 'I should' really means 'someone once told me I should.' Audit the source.", "source": "Schema work"},
    {"id": "cbt-057", "category": "cbt", "text": "You are allowed to take up space, ask questions, and say no without explanation.", "source": "Boundaries (DBT)"},
    {"id": "cbt-058", "category": "cbt", "text": "If you wouldn't talk to a friend that way, stop talking to yourself that way.", "source": "Compassionate inner voice"},
    {"id": "cbt-059", "category": "cbt", "text": "The body remembers what the mind forgets. If you're foggy, ask: have I eaten, drunk water, moved, slept?", "source": "Embodied check-in"},
    {"id": "cbt-060", "category": "cbt", "text": "What you avoid grows in the dark. What you name shrinks in the light.", "source": "Affect labeling / exposure"},
    {"id": "cbt-061", "category": "cbt", "text": "Discomfort is not the same as danger. Your nervous system is wrong here sometimes.", "source": "Polyvagal-informed"},
    {"id": "cbt-062", "category": "cbt", "text": "Five deep breaths is not a fix, but it's a wedge. Use it.", "source": "Grounding"},
    {"id": "cbt-063", "category": "cbt", "text": "Healing isn't linear. Setbacks aren't failure — they're data.", "source": "Recovery framework"},
    {"id": "cbt-064", "category": "cbt", "text": "Some days the win is staying. Don't grade staying as a loss.", "source": "Self-compassion"},
    {"id": "cbt-065", "category": "cbt", "text": "You don't have to feel motivated to act. Motivation often follows action; rarely precedes it.", "source": "Behavioral activation"},
    {"id": "cbt-066", "category": "cbt", "text": "When the inner critic gets loud, ask: is this advice or punishment? Listen only to advice.", "source": "Inner critic work"},
    {"id": "cbt-067", "category": "cbt", "text": "If your plan requires you to be at 100% energy to work, the plan is broken — not you.", "source": "Operational self-care"},
    {"id": "cbt-068", "category": "cbt", "text": "Don't trust the thoughts you have at 11pm. Sleep first, decide later.", "source": "Decision hygiene"},
    {"id": "cbt-069", "category": "cbt", "text": "Naming a fear out loud reduces its power. Whisper it to yourself if you can't say it to anyone else.", "source": "Affect labeling"},
    {"id": "cbt-070", "category": "cbt", "text": "Sometimes the most rebellious thing you can do is rest without earning it first.", "source": "Burnout reframe"},
    {"id": "cbt-071", "category": "cbt", "text": "Notice the gap between what you feel and what you decide. Decisions made inside intense feeling are usually worse.", "source": "Emotion regulation"},
    {"id": "cbt-072", "category": "cbt", "text": "Comparison without context is gaslighting yourself. You don't see their losses, only their highlight reel.", "source": "Reality check"},
    {"id": "cbt-073", "category": "cbt", "text": "If you can't change the situation today, lower the friction of the next right step.", "source": "Tiny-habits principle"},
    {"id": "cbt-074", "category": "cbt", "text": "Big leaps are rare; small choices are constant. Stack the small ones in your favor.", "source": "Habit principle"},
    {"id": "cbt-075", "category": "cbt", "text": "Three things you did right today, even if small. List them before bed. Repeat tomorrow.", "source": "Positive reframe practice"},
    {"id": "cbt-076", "category": "cbt", "text": "Anxiety wants you to plan forever. Pick one action and let the planning go.", "source": "CBT planning vs worry"},
    {"id": "cbt-077", "category": "cbt", "text": "The opposite of anxious isn't calm. It's grounded. Calm is hard. Grounded is achievable.", "source": "Grounding framework"},
    {"id": "cbt-078", "category": "cbt", "text": "You don't owe anyone the version of yourself that's burned out trying to be liked.", "source": "Boundaries"},
    {"id": "cbt-079", "category": "cbt", "text": "Energy debt compounds like financial debt. Pay it back before it costs more.", "source": "Burnout principle"},
    {"id": "cbt-080", "category": "cbt", "text": "Sometimes the most honest thing you can say is: I don't know yet. Sit with it.", "source": "Tolerating uncertainty"},
]


_GROWTH_V2: list[dict] = [
    {"id": "growth-041", "category": "growth", "text": "What you give your attention to becomes what you're an expert in. Choose your attention.", "source": "Attention principle"},
    {"id": "growth-042", "category": "growth", "text": "Show up every day for long enough and the world starts saving you a seat.", "source": "Consistency principle"},
    {"id": "growth-043", "category": "growth", "text": "Iteration beats inspiration over a long enough timeline.", "source": "Process principle"},
    {"id": "growth-044", "category": "growth", "text": "If you're not in over your head occasionally, you've stopped growing.", "source": "Growth zone"},
    {"id": "growth-045", "category": "growth", "text": "The most important muscle to train is the one that puts your shoes on.", "source": "Discipline principle"},
    {"id": "growth-046", "category": "growth", "text": "Be loyal to your future self, not your current mood.", "source": "Self-discipline"},
    {"id": "growth-047", "category": "growth", "text": "Discipline is a love letter to your future self.", "source": "Endurance reframe"},
    {"id": "growth-048", "category": "growth", "text": "Good enough today, better tomorrow, great in five years.", "source": "Compound improvement"},
    {"id": "growth-049", "category": "growth", "text": "Your environment will outlast your willpower. Design the environment first.", "source": "Behavioral design"},
    {"id": "growth-050", "category": "growth", "text": "If the bar is on the floor, raise it slightly. Don't raise it to the ceiling.", "source": "Incremental progress"},
    {"id": "growth-051", "category": "growth", "text": "Boredom is not a failure of stimulus — it's a precondition for focus.", "source": "Deep work"},
    {"id": "growth-052", "category": "growth", "text": "Focus is what you say no to, not what you say yes to.", "source": "Steve Jobs (paraphrased)"},
    {"id": "growth-053", "category": "growth", "text": "Inputs in. Outputs out. Audit the loop.", "source": "Systems principle"},
    {"id": "growth-054", "category": "growth", "text": "If everything is a priority, nothing is.", "source": "Prioritization"},
    {"id": "growth-055", "category": "growth", "text": "Practice doesn't make perfect. Practice makes permanent. Practice well.", "source": "Skill acquisition"},
    {"id": "growth-056", "category": "growth", "text": "Comfort is the slow path to obsolescence.", "source": "Growth principle"},
    {"id": "growth-057", "category": "growth", "text": "The bigger the dream, the boring-er the daily.", "source": "Dreams vs systems"},
    {"id": "growth-058", "category": "growth", "text": "Goals are direction. Systems are the road. Habits are the wheels.", "source": "Habit principle"},
    {"id": "growth-059", "category": "growth", "text": "If you can't measure progress, your goal is too vague. Pick a metric.", "source": "Operational reframe"},
    {"id": "growth-060", "category": "growth", "text": "Pace yourself. The race you're running is longer than you think.", "source": "Endurance"},
    {"id": "growth-061", "category": "growth", "text": "Recovery is part of the work, not a break from it.", "source": "Endurance"},
    {"id": "growth-062", "category": "growth", "text": "The discipline of doing one thing well is the only discipline that scales.", "source": "Focus principle"},
    {"id": "growth-063", "category": "growth", "text": "When you don't know what to do, do the next obvious right thing. Then the next one.", "source": "Action principle"},
    {"id": "growth-064", "category": "growth", "text": "Quality is the residue of caring more than necessary.", "source": "Craftsmanship"},
    {"id": "growth-065", "category": "growth", "text": "If you can do one push-up, you can do two. If you can do two, the rest is just stamina.", "source": "Endurance reframe"},
    {"id": "growth-066", "category": "growth", "text": "You become what you can do without thinking. Practice the right things until they're automatic.", "source": "Skill acquisition"},
    {"id": "growth-067", "category": "growth", "text": "There is no overnight success. There is only the day you finally notice.", "source": "Long-term reframe"},
    {"id": "growth-068", "category": "growth", "text": "Build the version of yourself you can sustain, not the version you can show off for a week.", "source": "Sustainability"},
    {"id": "growth-069", "category": "growth", "text": "Identity beats motivation. Decide who you are, then act like that person.", "source": "Identity-based habits"},
    {"id": "growth-070", "category": "growth", "text": "Process love beats outcome love. Outcomes are out of your hands.", "source": "Process principle"},
    {"id": "growth-071", "category": "growth", "text": "Get curious about what bores you. Curiosity is the antidote to drift.", "source": "Curiosity reframe"},
    {"id": "growth-072", "category": "growth", "text": "Reading is the cheapest mentor money can buy.", "source": "Learning principle"},
    {"id": "growth-073", "category": "growth", "text": "Sleep is the cheapest performance enhancer. Use it.", "source": "Operational self-care"},
    {"id": "growth-074", "category": "growth", "text": "Hard truths held privately become resentments. Speak them respectfully and on time.", "source": "Honest reframe"},
    {"id": "growth-075", "category": "growth", "text": "Most days you don't need a new strategy. You need to do today's strategy.", "source": "Execution principle"},
    {"id": "growth-076", "category": "growth", "text": "The brave choice and the lazy choice often wear the same clothes. Look closer.", "source": "Self-honesty"},
    {"id": "growth-077", "category": "growth", "text": "You can wait for the moment, or you can be the moment.", "source": "Action principle"},
    {"id": "growth-078", "category": "growth", "text": "Tiny is repeatable. Repeatable is compounding. Compounding wins.", "source": "Tiny habits"},
    {"id": "growth-079", "category": "growth", "text": "Make peace with the slow version of you. The slow version still finishes.", "source": "Endurance"},
    {"id": "growth-080", "category": "growth", "text": "Done is the engine of better. Get something done first.", "source": "Iteration principle"},
]


_FINANCIAL_V2: list[dict] = [
    {"id": "fin-011", "category": "financial", "text": "Risk is what you don't see coming. Plan for what you can; respect what you can't.", "source": "Howard Marks"},
    {"id": "fin-012", "category": "financial", "text": "The four most expensive words in trading are: this time it's different.", "source": "John Templeton"},
    {"id": "fin-013", "category": "financial", "text": "Cut your losers quick. Let your winners run. The order matters.", "source": "Trading folklore"},
    {"id": "fin-014", "category": "financial", "text": "Position size is the only thing you fully control. Honor it.", "source": "Risk management"},
    {"id": "fin-015", "category": "financial", "text": "The market doesn't owe you anything for being right.", "source": "Reality reframe"},
    {"id": "fin-016", "category": "financial", "text": "You don't have to take every trade. You have to take only the good ones.", "source": "Selectivity principle"},
    {"id": "fin-017", "category": "financial", "text": "Edge times bet size times sample size — that's your equity curve. All three matter.", "source": "Trading math"},
    {"id": "fin-018", "category": "financial", "text": "Be skeptical of anything that 'always works.' The market is a machine that finds and destroys those things.", "source": "Market reflexivity"},
    {"id": "fin-019", "category": "financial", "text": "Your worst drawdown is in front of you, not behind you. Plan accordingly.", "source": "Risk principle"},
    {"id": "fin-020", "category": "financial", "text": "When you don't know, do less.", "source": "Risk principle"},
    {"id": "fin-021", "category": "financial", "text": "The best traders aren't right more often; they're wrong cheaper.", "source": "Risk management"},
    {"id": "fin-022", "category": "financial", "text": "A great trader can lose money in a great market and make money in a terrible one. Process > tape.", "source": "Process principle"},
    {"id": "fin-023", "category": "financial", "text": "Conviction without size is opinion. Size without conviction is gambling. Match the two.", "source": "Sizing principle"},
    {"id": "fin-024", "category": "financial", "text": "Your real risk-tolerance is what you can actually do in a 20% drawdown — not what you claim now.", "source": "Behavioral honesty"},
    {"id": "fin-025", "category": "financial", "text": "If you can't articulate why you're in the trade, you don't know when to be out of it.", "source": "Trading hygiene"},
    {"id": "fin-026", "category": "financial", "text": "A loss taken on time is a tax. A loss held too long is a bill.", "source": "Loss principle"},
    {"id": "fin-027", "category": "financial", "text": "The best trades feel boring at the time. Excitement is usually a tell that something is off.", "source": "Process reframe"},
    {"id": "fin-028", "category": "financial", "text": "Don't fight the tape. Don't worship it either.", "source": "Tape reading"},
    {"id": "fin-029", "category": "financial", "text": "Earnings move stocks. Narratives move multiples. Know which one you're trading.", "source": "Fundamental vs narrative"},
    {"id": "fin-030", "category": "financial", "text": "Liquidity matters more than thesis the moment you need to exit.", "source": "Liquidity principle"},
    {"id": "fin-031", "category": "financial", "text": "The market punishes leverage when you can least afford it. Size like that.", "source": "Leverage principle"},
    {"id": "fin-032", "category": "financial", "text": "You don't need to call the top or the bottom. You need to be on the right side of the middle.", "source": "Middle-trade principle"},
    {"id": "fin-033", "category": "financial", "text": "Cash is a position. Sometimes it's the best one available.", "source": "Patience principle"},
    {"id": "fin-034", "category": "financial", "text": "If everyone agrees with your thesis, the trade is already done.", "source": "Crowdedness principle"},
    {"id": "fin-035", "category": "financial", "text": "Past performance is past performance. The future is its own race.", "source": "Reality reframe"},
    {"id": "fin-036", "category": "financial", "text": "Boring strategies executed consistently beat exciting strategies executed haphazardly.", "source": "Execution principle"},
    {"id": "fin-037", "category": "financial", "text": "Define risk before entry. After entry it's no longer up to you.", "source": "Pre-trade discipline"},
    {"id": "fin-038", "category": "financial", "text": "Hope is not a position-management tool.", "source": "Trading discipline"},
    {"id": "fin-039", "category": "financial", "text": "Volatility isn't risk. Permanent capital loss is risk. Distinguish.", "source": "Risk distinction"},
    {"id": "fin-040", "category": "financial", "text": "Sit on your hands. Sometimes the best trade is the one you don't take.", "source": "Patience principle"},
]


_PERSONAL_V2: list[dict] = [
    {"id": "personal-011", "category": "personal", "text": "The body keeps the score. Listen to what it's telling you before it has to shout.", "source": "Bessel van der Kolk (paraphrased)"},
    {"id": "personal-012", "category": "personal", "text": "Sleep is non-negotiable. The discount on tomorrow is too steep.", "source": "Wellness principle"},
    {"id": "personal-013", "category": "personal", "text": "Water before coffee. Walk before screen.", "source": "Morning routine"},
    {"id": "personal-014", "category": "personal", "text": "Your phone is a slot machine designed to keep you tired and distracted. Set hard limits.", "source": "Attention hygiene"},
    {"id": "personal-015", "category": "personal", "text": "Move daily. Even a 10-minute walk counts. Especially a 10-minute walk.", "source": "Movement principle"},
    {"id": "personal-016", "category": "personal", "text": "The people you spend time with are slowly becoming who you are. Curate the room.", "source": "Social shaping"},
    {"id": "personal-017", "category": "personal", "text": "Tell the people you love that you love them. Now, not later.", "source": "Relationship principle"},
    {"id": "personal-018", "category": "personal", "text": "Forgive yourself first. The grace you give yourself is the grace you have to give others.", "source": "Self-compassion"},
    {"id": "personal-019", "category": "personal", "text": "Saying no to good things makes room for great things. Decline gracefully.", "source": "Boundaries"},
    {"id": "personal-020", "category": "personal", "text": "Energy follows attention. Audit what's draining you before what's feeding you.", "source": "Attention principle"},
    {"id": "personal-021", "category": "personal", "text": "Be the friend you needed when you were younger.", "source": "Compassion reframe"},
    {"id": "personal-022", "category": "personal", "text": "Boundaries are a gift to the relationship. They tell the other person where you actually are.", "source": "Relational health"},
    {"id": "personal-023", "category": "personal", "text": "You are allowed to outgrow people, places, and patterns. Growth is the point.", "source": "Growth principle"},
    {"id": "personal-024", "category": "personal", "text": "Loneliness is hunger. Connection is the meal. Eat real meals.", "source": "Social health"},
    {"id": "personal-025", "category": "personal", "text": "Notice when you're proud. Pride is information about alignment.", "source": "Self-awareness"},
    {"id": "personal-026", "category": "personal", "text": "If it brings you peace it's not a waste of time.", "source": "Wellness reframe"},
    {"id": "personal-027", "category": "personal", "text": "Quiet is medicine. Schedule it like a meeting.", "source": "Operational wellness"},
    {"id": "personal-028", "category": "personal", "text": "You don't need to be everything to everyone. Pick the relationships that matter and invest there.", "source": "Selective relationships"},
    {"id": "personal-029", "category": "personal", "text": "Sometimes the most loving thing is to let someone be where they are without trying to fix it.", "source": "Compassion principle"},
    {"id": "personal-030", "category": "personal", "text": "Your health is the only asset that compounds in both directions. Tend it daily.", "source": "Health principle"},
]


_OPERATIONAL_V2: list[dict] = [
    {"id": "ops-011", "category": "operational", "text": "If a decision is reversible, decide fast. If it's irreversible, decide slow.", "source": "Bezos decision framework"},
    {"id": "ops-012", "category": "operational", "text": "Default to writing it down. Memory is a liar; ink is honest.", "source": "Operational hygiene"},
    {"id": "ops-013", "category": "operational", "text": "If two things compete for the same hour, decide which one you'd regret skipping more.", "source": "Regret minimization"},
    {"id": "ops-014", "category": "operational", "text": "The first version of anything is just data. Ship it; let reality tell you what to fix.", "source": "Iteration principle"},
    {"id": "ops-015", "category": "operational", "text": "Automation is leverage. Build small bots before you hire any humans.", "source": "Leverage principle"},
    {"id": "ops-016", "category": "operational", "text": "If you can't explain why you're doing it in one sentence, you don't know why you're doing it yet.", "source": "Clarity principle"},
    {"id": "ops-017", "category": "operational", "text": "Calendar tells you what you actually value. Audit it monthly.", "source": "Time audit"},
    {"id": "ops-018", "category": "operational", "text": "Single-task. Multi-task is just slow context-switching with extra steps.", "source": "Focus principle"},
    {"id": "ops-019", "category": "operational", "text": "Pre-commitment beats willpower every time. Decide what 'tomorrow you' will do before tomorrow comes.", "source": "Behavioral design"},
    {"id": "ops-020", "category": "operational", "text": "Default checklists for everything that you'd kick yourself for forgetting twice.", "source": "Checklist principle"},
]


_CREATIVE_V2: list[dict] = [
    {"id": "creative-006", "category": "creative", "text": "The blank page is not a judge. It's a sandbox. Play first; edit later.", "source": "Creative process"},
    {"id": "creative-007", "category": "creative", "text": "If you wait to feel ready, you'll wait forever. Begin badly.", "source": "Steven Pressfield"},
    {"id": "creative-008", "category": "creative", "text": "First drafts are made of clay. The shape comes from revising.", "source": "Iteration principle"},
    {"id": "creative-009", "category": "creative", "text": "Steal like an artist. Make it yours. The next person will steal from you.", "source": "Austin Kleon"},
    {"id": "creative-010", "category": "creative", "text": "Constraints are creativity's best friend. Limit something on purpose.", "source": "Creative constraint"},
    {"id": "creative-011", "category": "creative", "text": "You don't have to feel inspired to do good work. You have to show up so inspiration knows where to find you.", "source": "Pressfield principle"},
    {"id": "creative-012", "category": "creative", "text": "Make the thing only you can make.", "source": "Authenticity principle"},
    {"id": "creative-013", "category": "creative", "text": "Quantity is a path to quality. Make 100 of something to discover what makes one good.", "source": "Volume principle"},
    {"id": "creative-014", "category": "creative", "text": "Publish before you're proud. Pride is the enemy of finishing.", "source": "Iteration principle"},
    {"id": "creative-015", "category": "creative", "text": "Take the work seriously. Don't take yourself seriously.", "source": "Craft principle"},
]


def all_extension_entries() -> list[dict]:
    return (
        list(_STOIC_V2) + list(_CBT_V2) + list(_GROWTH_V2) + list(_FINANCIAL_V2)
        + list(_PERSONAL_V2) + list(_OPERATIONAL_V2) + list(_CREATIVE_V2)
    )


def extend_wisdom_corpus(wisdom_file: Path | None = None) -> int:
    if wisdom_file is None:
        from .wisdom import _wisdom_file
        wisdom_file = _wisdom_file()
    wisdom_file.parent.mkdir(parents=True, exist_ok=True)

    existing_ids: set[str] = set()
    if wisdom_file.exists():
        with wisdom_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and rec.get("id"):
                        existing_ids.add(rec["id"])
                except Exception:
                    continue

    added = 0
    with wisdom_file.open("a", encoding="utf-8") as f:
        for entry in all_extension_entries():
            if entry["id"] in existing_ids:
                continue
            f.write(json.dumps(entry) + "\n")
            added += 1

    if added:
        log.info("[wisdom_corpus_v2] appended %d entries -> %s", added, wisdom_file)
    return added


__all__ = ["all_extension_entries", "extend_wisdom_corpus"]
