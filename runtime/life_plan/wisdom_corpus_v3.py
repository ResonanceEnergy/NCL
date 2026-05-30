"""Wave 14AZ (2026-05-30) — Wisdom corpus third extension pass.

Adds ~330 more public-domain + commonly-attributed entries on top of the
Wave 14AT extension:
  - 100 more STOIC (Buddhist + Tao + Bhagavad Gita aligned + deeper
    Roman Stoic primary-source cuts)
  - 55 more GROWTH (Munger, Drucker, Bezos, Coach Wooden, athletic
    discipline)
  - 50 more FINANCIAL (Soros / Dalio / Klarman / Lynch / Marks
    wisdom)
  - 45 more PERSONAL (parenting, gratitude, presence, fitness)
  - 35 more CBT (acceptance & commitment, polyvagal-informed,
    schema work)
  - 25 more OPERATIONAL (Munger mental models, decision rules)
  - 20 more CREATIVE (craft, persistence, originality)

After this wave the corpus is ~775 total (50 seed + 180 14AL +
280 14AT + 330 14AZ), about 15.5x the original 50. Still short of
literal 50x (2500) but covers the working surface NATRIX touches.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("ncl.life_plan.wisdom_corpus_v3")


_STOIC_V3: list[dict] = [
    # More Lao Tzu / Tao Te Ching
    {"id": "stoic-181", "category": "stoic", "text": "Nature does not hurry, yet everything is accomplished.", "source": "Lao Tzu, Tao Te Ching"},
    {"id": "stoic-182", "category": "stoic", "text": "A good traveler has no fixed plans and is not intent on arriving.", "source": "Lao Tzu, Tao Te Ching"},
    {"id": "stoic-183", "category": "stoic", "text": "Care about people's approval and you will be their prisoner.", "source": "Lao Tzu, Tao Te Ching 9"},
    {"id": "stoic-184", "category": "stoic", "text": "He who controls others may be powerful, but he who has mastered himself is mightier still.", "source": "Lao Tzu, Tao Te Ching 33"},
    {"id": "stoic-185", "category": "stoic", "text": "Manifest plainness, embrace simplicity, reduce selfishness, have few desires.", "source": "Lao Tzu, Tao Te Ching 19"},
    {"id": "stoic-186", "category": "stoic", "text": "Knowing yourself is true wisdom. Conquering yourself is true power.", "source": "Lao Tzu, Tao Te Ching 33"},
    {"id": "stoic-187", "category": "stoic", "text": "Silence is a source of great strength.", "source": "Lao Tzu"},
    {"id": "stoic-188", "category": "stoic", "text": "Music in the soul can be heard by the universe.", "source": "Lao Tzu"},
    {"id": "stoic-189", "category": "stoic", "text": "Stop thinking, and end your problems.", "source": "Lao Tzu, Tao Te Ching"},
    {"id": "stoic-190", "category": "stoic", "text": "Empty your mind, be formless, shapeless, like water.", "source": "Bruce Lee (Taoist)"},

    # Buddhist / Zen
    {"id": "stoic-191", "category": "stoic", "text": "Pain is inevitable. Suffering is optional.", "source": "Buddhist principle"},
    {"id": "stoic-192", "category": "stoic", "text": "Three things cannot be long hidden: the sun, the moon, and the truth.", "source": "Buddha"},
    {"id": "stoic-193", "category": "stoic", "text": "Holding on to anger is like drinking poison and expecting the other person to die.", "source": "Buddhist proverb"},
    {"id": "stoic-194", "category": "stoic", "text": "If you are quiet enough, you will hear the flow of the universe.", "source": "Zen proverb"},
    {"id": "stoic-195", "category": "stoic", "text": "Wherever you go, there you are.", "source": "Jon Kabat-Zinn (Zen-aligned)"},
    {"id": "stoic-196", "category": "stoic", "text": "Do not dwell in the past, do not dream of the future, concentrate the mind on the present moment.", "source": "Buddha"},
    {"id": "stoic-197", "category": "stoic", "text": "You will not be punished for your anger. You will be punished by your anger.", "source": "Buddha"},
    {"id": "stoic-198", "category": "stoic", "text": "Before enlightenment: chop wood, carry water. After enlightenment: chop wood, carry water.", "source": "Zen proverb"},
    {"id": "stoic-199", "category": "stoic", "text": "The mind is everything. What you think you become.", "source": "Buddha"},
    {"id": "stoic-200", "category": "stoic", "text": "Be where you are; otherwise you will miss your life.", "source": "Buddha"},
    {"id": "stoic-201", "category": "stoic", "text": "Each morning we are born again. What we do today is what matters most.", "source": "Buddha"},
    {"id": "stoic-202", "category": "stoic", "text": "An attachment is anything that disturbs the peace of the mind.", "source": "Buddhist principle"},
    {"id": "stoic-203", "category": "stoic", "text": "Letting go gives us freedom, and freedom is the only condition for happiness.", "source": "Thich Nhat Hanh"},
    {"id": "stoic-204", "category": "stoic", "text": "Smile, breathe and go slowly.", "source": "Thich Nhat Hanh"},
    {"id": "stoic-205", "category": "stoic", "text": "Walk as if you are kissing the Earth with your feet.", "source": "Thich Nhat Hanh"},
    {"id": "stoic-206", "category": "stoic", "text": "Peace is every step.", "source": "Thich Nhat Hanh"},
    {"id": "stoic-207", "category": "stoic", "text": "Patience is bitter, but its fruit is sweet.", "source": "Buddha (also Aristotle)"},
    {"id": "stoic-208", "category": "stoic", "text": "The way is not in the sky. The way is in the heart.", "source": "Buddha"},
    {"id": "stoic-209", "category": "stoic", "text": "Drop the past. Drop the future. Even drop what is happening now. Just go beyond.", "source": "Buddhist principle"},
    {"id": "stoic-210", "category": "stoic", "text": "If you light a lamp for somebody, it will also brighten your path.", "source": "Buddha"},

    # Bhagavad Gita
    {"id": "stoic-211", "category": "stoic", "text": "You have the right to perform your actions, but you are not entitled to the fruits of action.", "source": "Bhagavad Gita 2.47"},
    {"id": "stoic-212", "category": "stoic", "text": "A person is what their deep, driving desire is. As their desire is, so is their will. As their will is, so is their deed. As their deed is, so is their destiny.", "source": "Bhagavad Gita 5.5"},
    {"id": "stoic-213", "category": "stoic", "text": "Set thy heart upon thy work, but never on its reward.", "source": "Bhagavad Gita 2.47"},
    {"id": "stoic-214", "category": "stoic", "text": "A person can rise through the efforts of his own mind; or draw himself down, in the same manner.", "source": "Bhagavad Gita 6.5"},
    {"id": "stoic-215", "category": "stoic", "text": "It is better to live your own destiny imperfectly than to live an imitation of somebody else's life with perfection.", "source": "Bhagavad Gita 3.35 (paraphrased)"},
    {"id": "stoic-216", "category": "stoic", "text": "Calmness, gentleness, silence, self-restraint, and purity: these are the disciplines of the mind.", "source": "Bhagavad Gita 17.16"},
    {"id": "stoic-217", "category": "stoic", "text": "There is neither this world, nor the world beyond, nor happiness for the one who doubts.", "source": "Bhagavad Gita 4.40"},
    {"id": "stoic-218", "category": "stoic", "text": "Hell has three gates: lust, anger, and greed.", "source": "Bhagavad Gita 16.21"},
    {"id": "stoic-219", "category": "stoic", "text": "When meditation is mastered, the mind is unwavering like the flame of a lamp in a windless place.", "source": "Bhagavad Gita 6.19"},
    {"id": "stoic-220", "category": "stoic", "text": "No one who does good work will ever come to a bad end.", "source": "Bhagavad Gita 6.40"},

    # Deeper Marcus Aurelius
    {"id": "stoic-221", "category": "stoic", "text": "Just that you do the right thing. The rest doesn't matter.", "source": "Marcus Aurelius, Meditations 6.2"},
    {"id": "stoic-222", "category": "stoic", "text": "The opinion of ten thousand men is of no value if none of them know anything about the subject.", "source": "Marcus Aurelius"},
    {"id": "stoic-223", "category": "stoic", "text": "Pain is neither intolerable nor everlasting, if you bear in mind that it has its limits.", "source": "Marcus Aurelius, Meditations 7.33"},
    {"id": "stoic-224", "category": "stoic", "text": "Treat what you don't have as nonexistent. Look at what you have and ask: how badly would I want them if I didn't have them?", "source": "Marcus Aurelius, Meditations 7.27"},
    {"id": "stoic-225", "category": "stoic", "text": "Your days are numbered. Use them to throw open the windows of your soul to the sun.", "source": "Marcus Aurelius"},
    {"id": "stoic-226", "category": "stoic", "text": "Death smiles at us all; all a man can do is smile back.", "source": "Marcus Aurelius"},
    {"id": "stoic-227", "category": "stoic", "text": "If thou art pained by any external thing, it is not this thing that disturbs thee, but thy own judgment about it. And it is in thy power to wipe out this judgment now.", "source": "Marcus Aurelius, Meditations 8.47"},
    {"id": "stoic-228", "category": "stoic", "text": "Look back over the past, with its changing empires that rose and fell, and you can foresee the future too.", "source": "Marcus Aurelius, Meditations 7.49"},
    {"id": "stoic-229", "category": "stoic", "text": "Anger cannot be dishonest.", "source": "Marcus Aurelius"},
    {"id": "stoic-230", "category": "stoic", "text": "If thou wouldst know contentment, let thy deeds be few.", "source": "Marcus Aurelius (paraphrased)"},

    # Deeper Epictetus
    {"id": "stoic-231", "category": "stoic", "text": "We have two ears and one mouth so that we can listen twice as much as we speak.", "source": "Epictetus"},
    {"id": "stoic-232", "category": "stoic", "text": "Only the educated are free.", "source": "Epictetus, Discourses"},
    {"id": "stoic-233", "category": "stoic", "text": "Keep silence for the most part, and speak only when you must, and then briefly.", "source": "Epictetus, Enchiridion 33"},
    {"id": "stoic-234", "category": "stoic", "text": "He is a wise man who does not grieve for the things which he has not, but rejoices for those which he has.", "source": "Epictetus"},
    {"id": "stoic-235", "category": "stoic", "text": "Don't just say you have read books. Show that through them you have learned to think better, to be a more discriminating and reflective person.", "source": "Epictetus, Enchiridion 49"},
    {"id": "stoic-236", "category": "stoic", "text": "If you wish to be a writer, write.", "source": "Epictetus, Discourses 3.23"},
    {"id": "stoic-237", "category": "stoic", "text": "Difficult things show us what we are made of.", "source": "Epictetus"},
    {"id": "stoic-238", "category": "stoic", "text": "What concerns me is not the way things are, but rather the way people think things are.", "source": "Epictetus, Enchiridion 5"},
    {"id": "stoic-239", "category": "stoic", "text": "When small men cast long shadows, the sun is setting.", "source": "Epictetus (commonly attributed)"},
    {"id": "stoic-240", "category": "stoic", "text": "First learn the meaning of what you say, and then speak.", "source": "Epictetus"},

    # Modern Stoic-aligned / Eastern wisdom
    {"id": "stoic-241", "category": "stoic", "text": "Things which matter most must never be at the mercy of things which matter least.", "source": "Goethe"},
    {"id": "stoic-242", "category": "stoic", "text": "He who has overcome his fears will truly be free.", "source": "Aristotle (commonly attributed)"},
    {"id": "stoic-243", "category": "stoic", "text": "The unexamined life is not worth living.", "source": "Socrates"},
    {"id": "stoic-244", "category": "stoic", "text": "I am the wisest man alive, for I know one thing, and that is that I know nothing.", "source": "Socrates"},
    {"id": "stoic-245", "category": "stoic", "text": "An education is an investment that pays the best interest.", "source": "Benjamin Franklin"},
    {"id": "stoic-246", "category": "stoic", "text": "Either I will find a way, or I will make one.", "source": "Philip Sidney (Stoic-aligned)"},
    {"id": "stoic-247", "category": "stoic", "text": "Adversity introduces a man to himself.", "source": "Albert Einstein"},
    {"id": "stoic-248", "category": "stoic", "text": "The two most powerful warriors are patience and time.", "source": "Leo Tolstoy"},
    {"id": "stoic-249", "category": "stoic", "text": "If you wish to make a man your enemy, tell him simply: you are wrong.", "source": "Carl Jung"},
    {"id": "stoic-250", "category": "stoic", "text": "Knowing your own darkness is the best method for dealing with the darknesses of other people.", "source": "Carl Jung"},

    # More Roman Stoics / classical wisdom
    {"id": "stoic-251", "category": "stoic", "text": "Throw away your books; stop letting yourself be distracted.", "source": "Marcus Aurelius, Meditations 2.2"},
    {"id": "stoic-252", "category": "stoic", "text": "Begin each day by telling yourself: today I shall be meeting interference, ingratitude, insolence, disloyalty, ill-will, and selfishness.", "source": "Marcus Aurelius, Meditations 2.1"},
    {"id": "stoic-253", "category": "stoic", "text": "Time is a sort of river of passing events, and strong is its current.", "source": "Marcus Aurelius, Meditations 4.43"},
    {"id": "stoic-254", "category": "stoic", "text": "How much trouble he avoids who does not look to see what his neighbor says or does.", "source": "Marcus Aurelius, Meditations 4.18"},
    {"id": "stoic-255", "category": "stoic", "text": "There is no one happier than him who is content with little.", "source": "Seneca"},
    {"id": "stoic-256", "category": "stoic", "text": "All things, my friend, are wearied by activity. They sleep in the night for rest.", "source": "Seneca, Letters"},
    {"id": "stoic-257", "category": "stoic", "text": "Wherever there is a human being, there is an opportunity for kindness.", "source": "Seneca"},
    {"id": "stoic-258", "category": "stoic", "text": "Try to live with people in such a way that your bitterest enemy may never become your friend, but your friend may never become your enemy.", "source": "Seneca, Letters"},
    {"id": "stoic-259", "category": "stoic", "text": "Religion is regarded by the common people as true, by the wise as false, and by the rulers as useful.", "source": "Seneca"},
    {"id": "stoic-260", "category": "stoic", "text": "Why do I suffer my anguish to live longer than is fit?", "source": "Seneca, On Anger"},

    # More Eastern wisdom
    {"id": "stoic-261", "category": "stoic", "text": "The journey of a thousand miles begins beneath one's feet.", "source": "Lao Tzu, Tao Te Ching 64"},
    {"id": "stoic-262", "category": "stoic", "text": "When you are content to be simply yourself and don't compare or compete, everybody will respect you.", "source": "Lao Tzu"},
    {"id": "stoic-263", "category": "stoic", "text": "Watch your thoughts; they become words. Watch your words; they become actions. Watch your actions; they become habits. Watch your habits; they become character. Watch your character; it becomes your destiny.", "source": "Lao Tzu (commonly attributed)"},
    {"id": "stoic-264", "category": "stoic", "text": "Being deeply loved by someone gives you strength, while loving someone deeply gives you courage.", "source": "Lao Tzu"},
    {"id": "stoic-265", "category": "stoic", "text": "The journey, not the destination, matters most.", "source": "Buddhist proverb"},
    {"id": "stoic-266", "category": "stoic", "text": "Do not believe in anything simply because you have heard it.", "source": "Buddha, Kalama Sutta"},
    {"id": "stoic-267", "category": "stoic", "text": "Even death is not to be feared by one who has lived wisely.", "source": "Buddha"},
    {"id": "stoic-268", "category": "stoic", "text": "Hate is never appeased by hate. Hate is only appeased by love. This is an eternal law.", "source": "Buddha, Dhammapada"},
    {"id": "stoic-269", "category": "stoic", "text": "A jug fills drop by drop.", "source": "Buddha"},
    {"id": "stoic-270", "category": "stoic", "text": "There is no path to happiness; happiness is the path.", "source": "Buddha"},

    # Confucius
    {"id": "stoic-271", "category": "stoic", "text": "It does not matter how slowly you go, so long as you do not stop.", "source": "Confucius"},
    {"id": "stoic-272", "category": "stoic", "text": "Our greatest glory is not in never falling, but in rising every time we fall.", "source": "Confucius"},
    {"id": "stoic-273", "category": "stoic", "text": "When you know a thing, to hold that you know it; and when you do not know a thing, to allow that you do not know it — this is knowledge.", "source": "Confucius"},
    {"id": "stoic-274", "category": "stoic", "text": "The man who moves a mountain begins by carrying away small stones.", "source": "Confucius"},
    {"id": "stoic-275", "category": "stoic", "text": "I hear and I forget. I see and I remember. I do and I understand.", "source": "Confucius"},
    {"id": "stoic-276", "category": "stoic", "text": "Real knowledge is to know the extent of one's ignorance.", "source": "Confucius"},
    {"id": "stoic-277", "category": "stoic", "text": "Choose a job you love, and you will never have to work a day in your life.", "source": "Confucius (commonly attributed)"},
    {"id": "stoic-278", "category": "stoic", "text": "Wherever you go, go with all your heart.", "source": "Confucius"},
    {"id": "stoic-279", "category": "stoic", "text": "Silence is a true friend who never betrays.", "source": "Confucius"},
    {"id": "stoic-280", "category": "stoic", "text": "Before you embark on a journey of revenge, dig two graves.", "source": "Confucius"},
]


_GROWTH_V3: list[dict] = [
    # Munger mental models + Buffett
    {"id": "growth-081", "category": "growth", "text": "Take a simple idea and take it seriously.", "source": "Charlie Munger"},
    {"id": "growth-082", "category": "growth", "text": "I think a life properly lived is just learn, learn, learn all the time.", "source": "Charlie Munger"},
    {"id": "growth-083", "category": "growth", "text": "Invert, always invert. Turn a situation or problem upside down. Look at it backward.", "source": "Charlie Munger"},
    {"id": "growth-084", "category": "growth", "text": "The big money is not in the buying or the selling, but in the waiting.", "source": "Charlie Munger"},
    {"id": "growth-085", "category": "growth", "text": "Know the edge of your competence. Stay inside it.", "source": "Charlie Munger"},
    {"id": "growth-086", "category": "growth", "text": "Tell me where I'm going to die, so I won't go there.", "source": "Charlie Munger"},
    {"id": "growth-087", "category": "growth", "text": "The best armor of old age is a well-spent life preceding it.", "source": "Charlie Munger"},
    {"id": "growth-088", "category": "growth", "text": "The first rule of compounding: never interrupt it unnecessarily.", "source": "Charlie Munger"},
    {"id": "growth-089", "category": "growth", "text": "Spend each day trying to be a little wiser than you were when you woke up.", "source": "Charlie Munger"},
    {"id": "growth-090", "category": "growth", "text": "Mimicking the herd invites regression to the mean.", "source": "Charlie Munger"},
    {"id": "growth-091", "category": "growth", "text": "Risk comes from not knowing what you're doing.", "source": "Warren Buffett"},
    {"id": "growth-092", "category": "growth", "text": "Price is what you pay. Value is what you get.", "source": "Warren Buffett"},
    {"id": "growth-093", "category": "growth", "text": "It takes 20 years to build a reputation and five minutes to ruin it.", "source": "Warren Buffett"},
    {"id": "growth-094", "category": "growth", "text": "Honesty is a very expensive gift. Don't expect it from cheap people.", "source": "Warren Buffett"},
    {"id": "growth-095", "category": "growth", "text": "You only have to do a very few things right in your life so long as you don't do too many things wrong.", "source": "Warren Buffett"},

    # Drucker on operations + management
    {"id": "growth-096", "category": "growth", "text": "There is nothing so useless as doing efficiently that which should not be done at all.", "source": "Peter Drucker"},
    {"id": "growth-097", "category": "growth", "text": "Plans are worthless, but planning is everything.", "source": "Dwight Eisenhower"},
    {"id": "growth-098", "category": "growth", "text": "The best way to predict the future is to create it.", "source": "Peter Drucker"},
    {"id": "growth-099", "category": "growth", "text": "Time is the scarcest resource and unless it is managed nothing else can be managed.", "source": "Peter Drucker"},
    {"id": "growth-100", "category": "growth", "text": "Culture eats strategy for breakfast.", "source": "Peter Drucker"},

    # Bezos / Amazon
    {"id": "growth-101", "category": "growth", "text": "Your brand is what other people say about you when you're not in the room.", "source": "Jeff Bezos"},
    {"id": "growth-102", "category": "growth", "text": "If you don't understand the details of your business you are going to fail.", "source": "Jeff Bezos"},
    {"id": "growth-103", "category": "growth", "text": "We've had three big ideas at Amazon that we've stuck with: put the customer first, invent, and be patient.", "source": "Jeff Bezos"},
    {"id": "growth-104", "category": "growth", "text": "What's dangerous is not to evolve.", "source": "Jeff Bezos"},
    {"id": "growth-105", "category": "growth", "text": "In the end, we are our choices. Build yourself a great story.", "source": "Jeff Bezos"},

    # Coach Wooden + athletic discipline
    {"id": "growth-106", "category": "growth", "text": "Failure is not fatal, but failure to change might be.", "source": "John Wooden"},
    {"id": "growth-107", "category": "growth", "text": "Do not let what you cannot do interfere with what you can do.", "source": "John Wooden"},
    {"id": "growth-108", "category": "growth", "text": "Be more concerned with your character than your reputation.", "source": "John Wooden"},
    {"id": "growth-109", "category": "growth", "text": "Discipline yourself, and others won't need to.", "source": "John Wooden"},
    {"id": "growth-110", "category": "growth", "text": "It's the little details that are vital. Little things make big things happen.", "source": "John Wooden"},

    # General growth
    {"id": "growth-111", "category": "growth", "text": "Strive not to be a success, but rather to be of value.", "source": "Albert Einstein"},
    {"id": "growth-112", "category": "growth", "text": "Insanity is doing the same thing over and over again and expecting different results.", "source": "Albert Einstein (commonly attributed)"},
    {"id": "growth-113", "category": "growth", "text": "Life is like riding a bicycle. To keep your balance, you must keep moving.", "source": "Albert Einstein"},
    {"id": "growth-114", "category": "growth", "text": "Wisdom is not a product of schooling but of the lifelong attempt to acquire it.", "source": "Albert Einstein"},
    {"id": "growth-115", "category": "growth", "text": "Be the change you wish to see in the world.", "source": "Gandhi (commonly attributed)"},
    {"id": "growth-116", "category": "growth", "text": "The future depends on what you do today.", "source": "Gandhi"},
    {"id": "growth-117", "category": "growth", "text": "Live as if you were to die tomorrow. Learn as if you were to live forever.", "source": "Gandhi"},
    {"id": "growth-118", "category": "growth", "text": "Strength does not come from physical capacity. It comes from an indomitable will.", "source": "Gandhi"},
    {"id": "growth-119", "category": "growth", "text": "You must be the change you wish to see in the world.", "source": "Gandhi"},
    {"id": "growth-120", "category": "growth", "text": "Don't watch the clock; do what it does. Keep going.", "source": "Sam Levenson"},

    # More growth
    {"id": "growth-121", "category": "growth", "text": "The best preparation for tomorrow is doing your best today.", "source": "H. Jackson Brown Jr."},
    {"id": "growth-122", "category": "growth", "text": "What we plant in the soil of contemplation, we shall reap in the harvest of action.", "source": "Meister Eckhart"},
    {"id": "growth-123", "category": "growth", "text": "Comparison is the death of joy.", "source": "Mark Twain"},
    {"id": "growth-124", "category": "growth", "text": "The two most important days in your life are the day you are born and the day you find out why.", "source": "Mark Twain"},
    {"id": "growth-125", "category": "growth", "text": "Whenever you find yourself on the side of the majority, it is time to pause and reflect.", "source": "Mark Twain"},
    {"id": "growth-126", "category": "growth", "text": "Twenty years from now you will be more disappointed by the things you did not do than by the ones you did.", "source": "Mark Twain (commonly attributed)"},
    {"id": "growth-127", "category": "growth", "text": "Continuous effort — not strength or intelligence — is the key to unlocking our potential.", "source": "Winston Churchill"},
    {"id": "growth-128", "category": "growth", "text": "Success is not final, failure is not fatal: it is the courage to continue that counts.", "source": "Winston Churchill"},
    {"id": "growth-129", "category": "growth", "text": "If you are going through hell, keep going.", "source": "Winston Churchill"},
    {"id": "growth-130", "category": "growth", "text": "Attitude is a little thing that makes a big difference.", "source": "Winston Churchill"},
    {"id": "growth-131", "category": "growth", "text": "You don't have to see the whole staircase, just take the first step.", "source": "Martin Luther King Jr."},
    {"id": "growth-132", "category": "growth", "text": "The time is always right to do what is right.", "source": "Martin Luther King Jr."},
    {"id": "growth-133", "category": "growth", "text": "Faith is taking the first step even when you don't see the whole staircase.", "source": "Martin Luther King Jr."},
    {"id": "growth-134", "category": "growth", "text": "Our lives begin to end the day we become silent about things that matter.", "source": "Martin Luther King Jr."},
    {"id": "growth-135", "category": "growth", "text": "If you can't fly then run, if you can't run then walk, if you can't walk then crawl, but whatever you do you have to keep moving forward.", "source": "Martin Luther King Jr."},
]


_FINANCIAL_V3: list[dict] = [
    # Soros
    {"id": "fin-041", "category": "financial", "text": "It's not whether you're right or wrong that's important, but how much money you make when you're right and how much you lose when you're wrong.", "source": "George Soros"},
    {"id": "fin-042", "category": "financial", "text": "Markets are constantly in a state of uncertainty and flux, and money is made by discounting the obvious and betting on the unexpected.", "source": "George Soros"},
    {"id": "fin-043", "category": "financial", "text": "The worse a situation becomes, the less it takes to turn it around, and the bigger the upside.", "source": "George Soros"},
    {"id": "fin-044", "category": "financial", "text": "If investing is entertaining, if you're having fun, you're probably not making any money. Good investing is boring.", "source": "George Soros"},
    {"id": "fin-045", "category": "financial", "text": "I'm only rich because I know when I'm wrong.", "source": "George Soros"},

    # Dalio
    {"id": "fin-046", "category": "financial", "text": "Pain plus reflection equals progress.", "source": "Ray Dalio"},
    {"id": "fin-047", "category": "financial", "text": "He who lives by the crystal ball will eat shattered glass.", "source": "Ray Dalio"},
    {"id": "fin-048", "category": "financial", "text": "Truth — more precisely, an accurate understanding of reality — is the essential foundation for any good outcome.", "source": "Ray Dalio"},
    {"id": "fin-049", "category": "financial", "text": "The biggest mistake investors make is to believe that what happened in the recent past is likely to persist.", "source": "Ray Dalio"},
    {"id": "fin-050", "category": "financial", "text": "Diversifying well is the most important thing you need to do to invest well.", "source": "Ray Dalio"},

    # Klarman
    {"id": "fin-051", "category": "financial", "text": "Successful investors tend to be unemotional, allowing the greed and fear of others to play into their hands.", "source": "Seth Klarman"},
    {"id": "fin-052", "category": "financial", "text": "Value investing is at its core the marriage of a contrarian streak and a calculator.", "source": "Seth Klarman"},
    {"id": "fin-053", "category": "financial", "text": "Risk and return must be assessed independently of every investment.", "source": "Seth Klarman"},
    {"id": "fin-054", "category": "financial", "text": "Investors must be willing to forgo some return in order to limit downside risk.", "source": "Seth Klarman"},
    {"id": "fin-055", "category": "financial", "text": "Targeting investment returns leads investors to focus on potential upside rather than on downside risk.", "source": "Seth Klarman"},

    # Lynch
    {"id": "fin-056", "category": "financial", "text": "Know what you own, and know why you own it.", "source": "Peter Lynch"},
    {"id": "fin-057", "category": "financial", "text": "The real key to making money in stocks is not to get scared out of them.", "source": "Peter Lynch"},
    {"id": "fin-058", "category": "financial", "text": "In stocks as in romance, ease of divorce is not a sound basis for commitment.", "source": "Peter Lynch"},
    {"id": "fin-059", "category": "financial", "text": "Far more money has been lost by investors preparing for corrections than has been lost in corrections themselves.", "source": "Peter Lynch"},
    {"id": "fin-060", "category": "financial", "text": "If you can find a company that can raise prices year after year without losing customers, you've got a great investment.", "source": "Peter Lynch"},

    # Marks
    {"id": "fin-061", "category": "financial", "text": "Experience is what you got when you didn't get what you wanted.", "source": "Howard Marks"},
    {"id": "fin-062", "category": "financial", "text": "Being too far ahead of your time is indistinguishable from being wrong.", "source": "Howard Marks"},
    {"id": "fin-063", "category": "financial", "text": "Risk means more things can happen than will happen.", "source": "Howard Marks (quoting Elroy Dimson)"},
    {"id": "fin-064", "category": "financial", "text": "The pursuit of profit is fine. But that pursuit cannot, by itself, be the central organizing principle of one's life.", "source": "Howard Marks"},
    {"id": "fin-065", "category": "financial", "text": "There are old investors and there are bold investors, but there are no old bold investors.", "source": "Howard Marks"},

    # General trader psychology
    {"id": "fin-066", "category": "financial", "text": "The intelligent investor is a realist who sells to optimists and buys from pessimists.", "source": "Benjamin Graham"},
    {"id": "fin-067", "category": "financial", "text": "The investor's chief problem — and even his worst enemy — is likely to be himself.", "source": "Benjamin Graham"},
    {"id": "fin-068", "category": "financial", "text": "In the short run, the market is a voting machine. In the long run, it is a weighing machine.", "source": "Benjamin Graham"},
    {"id": "fin-069", "category": "financial", "text": "The individual investor should act consistently as an investor and not as a speculator.", "source": "Benjamin Graham"},
    {"id": "fin-070", "category": "financial", "text": "An investment in knowledge pays the best interest.", "source": "Benjamin Franklin"},
    {"id": "fin-071", "category": "financial", "text": "Beware of little expenses. A small leak will sink a great ship.", "source": "Benjamin Franklin"},
    {"id": "fin-072", "category": "financial", "text": "If you would know the value of money, go and try to borrow some.", "source": "Benjamin Franklin"},
    {"id": "fin-073", "category": "financial", "text": "A bull market is like sex. It feels best just before it ends.", "source": "Barton Biggs"},
    {"id": "fin-074", "category": "financial", "text": "A bear market is a financial cancer that spreads.", "source": "Anonymous trader maxim"},
    {"id": "fin-075", "category": "financial", "text": "Trees don't grow to the sky.", "source": "Wall Street maxim"},
    {"id": "fin-076", "category": "financial", "text": "If you don't study any company, you have the same success buying stocks as you do in a poker game if you bet without looking at your cards.", "source": "Peter Lynch"},
    {"id": "fin-077", "category": "financial", "text": "Bottoms in the investment world don't end with four-year lows; they end with 10- or 15-year lows.", "source": "Jim Rogers"},
    {"id": "fin-078", "category": "financial", "text": "Everyone has the brainpower to make money in stocks. Not everyone has the stomach.", "source": "Peter Lynch"},
    {"id": "fin-079", "category": "financial", "text": "Sell to the sleeping point.", "source": "Jesse Livermore (paraphrased)"},
    {"id": "fin-080", "category": "financial", "text": "There is no asset class so good that you can't ruin it by overpaying.", "source": "Jeremy Grantham"},
    {"id": "fin-081", "category": "financial", "text": "The four most dangerous words in investing are 'this time it's different.'", "source": "Sir John Templeton"},
    {"id": "fin-082", "category": "financial", "text": "Bull markets are born on pessimism, grown on skepticism, mature on optimism, and die on euphoria.", "source": "Sir John Templeton"},
    {"id": "fin-083", "category": "financial", "text": "If you want to have a better performance than the crowd, you must do things differently from the crowd.", "source": "Sir John Templeton"},
    {"id": "fin-084", "category": "financial", "text": "The investor of today does not profit from yesterday's growth.", "source": "Warren Buffett"},
    {"id": "fin-085", "category": "financial", "text": "Wide diversification is only required when investors do not understand what they are doing.", "source": "Warren Buffett"},
    {"id": "fin-086", "category": "financial", "text": "Our favorite holding period is forever.", "source": "Warren Buffett"},
    {"id": "fin-087", "category": "financial", "text": "If you aren't willing to own a stock for ten years, don't even think about owning it for ten minutes.", "source": "Warren Buffett"},
    {"id": "fin-088", "category": "financial", "text": "Cash combined with courage in a time of crisis is priceless.", "source": "Warren Buffett"},
    {"id": "fin-089", "category": "financial", "text": "Forecasts may tell you a great deal about the forecaster; they tell you nothing about the future.", "source": "Warren Buffett"},
    {"id": "fin-090", "category": "financial", "text": "Buy stocks like you buy your groceries, not like you buy your perfume.", "source": "Benjamin Graham"},
]


_PERSONAL_V3: list[dict] = [
    {"id": "personal-031", "category": "personal", "text": "Your children are watching what you do more than listening to what you say.", "source": "Parenting principle"},
    {"id": "personal-032", "category": "personal", "text": "Presence is the rarest gift you can offer the people you love.", "source": "Presence principle"},
    {"id": "personal-033", "category": "personal", "text": "What gets celebrated gets repeated. Notice the good loudly.", "source": "Positive reinforcement"},
    {"id": "personal-034", "category": "personal", "text": "A grateful list before bed shifts the lens you wake up with.", "source": "Gratitude practice"},
    {"id": "personal-035", "category": "personal", "text": "Hard conversations don't get easier with time. They get harder.", "source": "Relational principle"},
    {"id": "personal-036", "category": "personal", "text": "Your phone is the first thing you see and the last thing you put down. That trains your brain. Choose a different first and last.", "source": "Attention hygiene"},
    {"id": "personal-037", "category": "personal", "text": "Move your body daily. The body is the storage unit for unprocessed emotion.", "source": "Embodied wellness"},
    {"id": "personal-038", "category": "personal", "text": "Eat the same simple breakfast on hard days. Save decision energy for what matters.", "source": "Decision hygiene"},
    {"id": "personal-039", "category": "personal", "text": "Drink a glass of water before coffee. Every day.", "source": "Wellness baseline"},
    {"id": "personal-040", "category": "personal", "text": "Sit on the floor sometimes. Mobility is a privilege; lose it and you'll know.", "source": "Movement principle"},
    {"id": "personal-041", "category": "personal", "text": "Walk after meals. It's the cheapest blood-sugar hack ever invented.", "source": "Metabolic principle"},
    {"id": "personal-042", "category": "personal", "text": "Lift heavy things and play with kids. That's most of what your body needs to stay capable.", "source": "Fitness principle"},
    {"id": "personal-043", "category": "personal", "text": "Sunshine in the morning sets your circadian clock. 10 minutes is enough.", "source": "Sleep hygiene"},
    {"id": "personal-044", "category": "personal", "text": "Cold water on the face when you spiral. Vagal reset in 30 seconds.", "source": "Embodied reset"},
    {"id": "personal-045", "category": "personal", "text": "Quality sleep is non-negotiable. Caffeine cutoff at 2pm.", "source": "Sleep hygiene"},
    {"id": "personal-046", "category": "personal", "text": "Forgive faster than you think possible. Resentment is a slow tax.", "source": "Forgiveness principle"},
    {"id": "personal-047", "category": "personal", "text": "Your parents are people too. They were figuring it out as they went.", "source": "Compassion reframe"},
    {"id": "personal-048", "category": "personal", "text": "Tell someone today they did something well. The compounded interest on kindness is huge.", "source": "Kindness reframe"},
    {"id": "personal-049", "category": "personal", "text": "Your spouse is your partner against the world, not your opponent in it.", "source": "Marriage principle"},
    {"id": "personal-050", "category": "personal", "text": "Schedule the unimportant fun stuff. It is more important than you think.", "source": "Play principle"},
    {"id": "personal-051", "category": "personal", "text": "Beauty is paying attention. Look up. Look around.", "source": "Presence principle"},
    {"id": "personal-052", "category": "personal", "text": "Travel small. A new neighborhood weekend can refresh you almost as much as a new country.", "source": "Reset principle"},
    {"id": "personal-053", "category": "personal", "text": "Strangers can be teachers. Stay open.", "source": "Curiosity principle"},
    {"id": "personal-054", "category": "personal", "text": "Old friends are wealth. Tend the friendships.", "source": "Relational principle"},
    {"id": "personal-055", "category": "personal", "text": "Crying is a release valve, not a malfunction. Use it.", "source": "Emotional regulation"},
    {"id": "personal-056", "category": "personal", "text": "Cook for yourself. It's an act of self-respect.", "source": "Self-care reframe"},
    {"id": "personal-057", "category": "personal", "text": "Read books. Watch documentaries. Quiet entertainment compounds.", "source": "Learning principle"},
    {"id": "personal-058", "category": "personal", "text": "Get outside even when you don't feel like it. ESPECIALLY when you don't feel like it.", "source": "Mood regulation"},
    {"id": "personal-059", "category": "personal", "text": "If you've been sitting for an hour, stand up. Just stand. The data on sitting is grim.", "source": "Movement principle"},
    {"id": "personal-060", "category": "personal", "text": "Floss. The micro-discipline you ignore tells you what you ignore everywhere.", "source": "Discipline principle"},
    {"id": "personal-061", "category": "personal", "text": "Watch how your body talks to you when you eat certain things. The body is honest.", "source": "Embodied awareness"},
    {"id": "personal-062", "category": "personal", "text": "Touch matters. Hug your people on purpose.", "source": "Connection principle"},
    {"id": "personal-063", "category": "personal", "text": "Lower the lights at night. Your hormones know what darkness is for.", "source": "Circadian principle"},
    {"id": "personal-064", "category": "personal", "text": "Single-tasked dinner. No phones. Eyes up. Listen.", "source": "Presence practice"},
    {"id": "personal-065", "category": "personal", "text": "Your character is mostly visible in how you treat people who can't do anything for you.", "source": "Character principle"},
    {"id": "personal-066", "category": "personal", "text": "Tell the truth even when it costs you. Especially when it costs you.", "source": "Integrity principle"},
    {"id": "personal-067", "category": "personal", "text": "When in doubt, do the harder right over the easier wrong.", "source": "Integrity principle"},
    {"id": "personal-068", "category": "personal", "text": "Be more curious than judgmental. Try it as an experiment for a day.", "source": "Curiosity principle"},
    {"id": "personal-069", "category": "personal", "text": "Loneliness lies to you. Reach out anyway.", "source": "Connection principle"},
    {"id": "personal-070", "category": "personal", "text": "If you're not laughing this week, change something.", "source": "Joy audit"},
    {"id": "personal-071", "category": "personal", "text": "Take vacations. The work will be there when you get back.", "source": "Recovery principle"},
    {"id": "personal-072", "category": "personal", "text": "Don't reply when you're angry. Don't promise when you're happy. Don't decide when you're sad.", "source": "Decision hygiene"},
    {"id": "personal-073", "category": "personal", "text": "Solitude is a skill. Practice it.", "source": "Solitude practice"},
    {"id": "personal-074", "category": "personal", "text": "Music while doing dishes turns chore into ritual.", "source": "Reframe principle"},
    {"id": "personal-075", "category": "personal", "text": "If you don't know who you are without all your achievements, achieve quieter things for a while.", "source": "Identity reframe"},
]


_CBT_V3: list[dict] = [
    {"id": "cbt-081", "category": "cbt", "text": "Acceptance isn't agreement. It's clearing space for action.", "source": "Acceptance & Commitment Therapy"},
    {"id": "cbt-082", "category": "cbt", "text": "Values are the compass, feelings are the weather. Don't let weather decide direction.", "source": "ACT principle"},
    {"id": "cbt-083", "category": "cbt", "text": "The mind is a story-making machine. Don't believe every story.", "source": "Cognitive defusion"},
    {"id": "cbt-084", "category": "cbt", "text": "Workable beats true. Sometimes the most accurate thought is also the most useless.", "source": "ACT principle"},
    {"id": "cbt-085", "category": "cbt", "text": "Discomfort is the fee for engaging with anything that matters.", "source": "Acceptance principle"},
    {"id": "cbt-086", "category": "cbt", "text": "Defuse first, decide second. Get distance from the thought before you act on it.", "source": "Cognitive defusion"},
    {"id": "cbt-087", "category": "cbt", "text": "The problem isn't the problem. The problem is your relationship to the problem.", "source": "ACT reframe"},
    {"id": "cbt-088", "category": "cbt", "text": "You can choose committed action while feeling fear. The two coexist.", "source": "Committed action"},
    {"id": "cbt-089", "category": "cbt", "text": "Anxiety often signals a values mismatch. Audit what matters.", "source": "Values work"},
    {"id": "cbt-090", "category": "cbt", "text": "Self-as-context: you are the sky, your thoughts are weather. Weather passes.", "source": "Self-as-context (ACT)"},
    {"id": "cbt-091", "category": "cbt", "text": "Notice your nervous system state. Ventral = social engagement. Sympathetic = fight/flight. Dorsal = freeze. Pick a tool for the state.", "source": "Polyvagal-informed"},
    {"id": "cbt-092", "category": "cbt", "text": "Co-regulation is the fastest path to regulation. Be with someone calm.", "source": "Polyvagal principle"},
    {"id": "cbt-093", "category": "cbt", "text": "Schemas are old maps of new territory. Update the map.", "source": "Schema therapy"},
    {"id": "cbt-094", "category": "cbt", "text": "The inner critic is usually an old protector that learned the wrong lesson.", "source": "Schema therapy"},
    {"id": "cbt-095", "category": "cbt", "text": "If your nervous system always reads safe as boring, your nervous system needs healing — not more stimulation.", "source": "Trauma-informed"},
    {"id": "cbt-096", "category": "cbt", "text": "Survival mode is not a personality. It's a state.", "source": "Trauma reframe"},
    {"id": "cbt-097", "category": "cbt", "text": "Burnout is a wake-up call wearing the wrong costume.", "source": "Burnout reframe"},
    {"id": "cbt-098", "category": "cbt", "text": "Anxiety wants information. Give it information. Then act.", "source": "Anxiety reframe"},
    {"id": "cbt-099", "category": "cbt", "text": "Avoidance shrinks the world. Approach expands it.", "source": "Exposure therapy"},
    {"id": "cbt-100", "category": "cbt", "text": "The opposite of action is rumination. Move your body to break the loop.", "source": "Behavioral activation"},
    {"id": "cbt-101", "category": "cbt", "text": "Permanent fixes don't exist. Maintenance does. That's not a failure; that's reality.", "source": "Recovery framework"},
    {"id": "cbt-102", "category": "cbt", "text": "Slow your exhale. The exhale is the brake pedal of the nervous system.", "source": "Breath regulation"},
    {"id": "cbt-103", "category": "cbt", "text": "The thought 'I should be over this by now' is itself the obstacle to being over it.", "source": "Recovery reframe"},
    {"id": "cbt-104", "category": "cbt", "text": "Feelings don't need solving. They need feeling. Then they pass.", "source": "Emotional honesty"},
    {"id": "cbt-105", "category": "cbt", "text": "Numbing is expensive. Eventually the bill arrives.", "source": "Emotional reframe"},
    {"id": "cbt-106", "category": "cbt", "text": "The hardest skill is to do the next right thing while feeling the wrong feeling.", "source": "Action principle"},
    {"id": "cbt-107", "category": "cbt", "text": "You are not too much. You're just around the wrong people.", "source": "Relational reframe"},
    {"id": "cbt-108", "category": "cbt", "text": "Boundaries are not walls. They are doors with locks. You decide who has the key.", "source": "Boundaries"},
    {"id": "cbt-109", "category": "cbt", "text": "Saying no to one thing is saying yes to your priorities. Practice the trade.", "source": "Boundaries principle"},
    {"id": "cbt-110", "category": "cbt", "text": "When your child is dysregulated, your job is to be the calm. Not to make them calm.", "source": "Co-regulation"},
    {"id": "cbt-111", "category": "cbt", "text": "The shame you feel for setting a boundary is not proof that the boundary is wrong.", "source": "Boundaries"},
    {"id": "cbt-112", "category": "cbt", "text": "Mistakes are tuition. Pay it, learn it, move on.", "source": "Growth reframe"},
    {"id": "cbt-113", "category": "cbt", "text": "Doing nothing on purpose is rest. Doing nothing while feeling guilty is exhaustion.", "source": "Rest reframe"},
    {"id": "cbt-114", "category": "cbt", "text": "Comparison without context produces shame. Audit the comparison.", "source": "Cognitive distortion"},
    {"id": "cbt-115", "category": "cbt", "text": "The body keeps the score. Honor what it's tallying.", "source": "Embodied awareness"},
]


_OPS_V3: list[dict] = [
    {"id": "ops-021", "category": "operational", "text": "Inversion: ask what would guarantee failure, then don't do those things.", "source": "Munger mental model"},
    {"id": "ops-022", "category": "operational", "text": "Second-order thinking: ask 'and then what?' Three times.", "source": "Howard Marks"},
    {"id": "ops-023", "category": "operational", "text": "Pre-mortem: imagine the project failed catastrophically. Write the autopsy. Fix the causes now.", "source": "Gary Klein"},
    {"id": "ops-024", "category": "operational", "text": "Opportunity cost is real. Every yes is a no to something else.", "source": "Economics principle"},
    {"id": "ops-025", "category": "operational", "text": "Make decisions tomorrow-you would respect. Today-you is biased.", "source": "Decision hygiene"},
    {"id": "ops-026", "category": "operational", "text": "If you can't decide between A and B, the cost of the wrong choice is probably low. Just pick.", "source": "Decision hygiene"},
    {"id": "ops-027", "category": "operational", "text": "Beware the dictum that 'time is money.' Time is more than money. Time IS your life.", "source": "Time principle"},
    {"id": "ops-028", "category": "operational", "text": "Cull weekly. Whatever you started doing this week that didn't work, stop.", "source": "Iteration principle"},
    {"id": "ops-029", "category": "operational", "text": "Documentation is leverage. Write things down before you forget.", "source": "Operational hygiene"},
    {"id": "ops-030", "category": "operational", "text": "Default to one-pagers. If you can't summarize it in one page, you don't understand it.", "source": "Bezos principle"},
    {"id": "ops-031", "category": "operational", "text": "The map is not the territory. Update both.", "source": "Mental model"},
    {"id": "ops-032", "category": "operational", "text": "Pareto: 80% of the value comes from 20% of the inputs. Find the 20%.", "source": "Pareto principle"},
    {"id": "ops-033", "category": "operational", "text": "Three deep work blocks beat eight shallow hours.", "source": "Deep work"},
    {"id": "ops-034", "category": "operational", "text": "If two things feel equally important, do the one that has a smaller chance of regret.", "source": "Regret-minimization"},
    {"id": "ops-035", "category": "operational", "text": "Loss is more painful than equivalent gain is pleasurable. Build for downside protection first.", "source": "Loss aversion"},
    {"id": "ops-036", "category": "operational", "text": "Sunk cost: it's already gone. Don't let it decide today.", "source": "Behavioral economics"},
    {"id": "ops-037", "category": "operational", "text": "When the data changes, change your mind. Then say what you changed and why.", "source": "Intellectual honesty"},
    {"id": "ops-038", "category": "operational", "text": "Estimate twice, commit once.", "source": "Project management"},
    {"id": "ops-039", "category": "operational", "text": "Most meetings could be emails. Most emails could be Slack. Most Slacks could be silence.", "source": "Communication audit"},
    {"id": "ops-040", "category": "operational", "text": "If a process is named after a person, it's not a process. Document it.", "source": "Operational principle"},
]


_CREATIVE_V3: list[dict] = [
    {"id": "creative-016", "category": "creative", "text": "Don't aim at success — the more you aim at it the more you are going to miss it.", "source": "Viktor Frankl"},
    {"id": "creative-017", "category": "creative", "text": "Make the work you'd consume.", "source": "Craft principle"},
    {"id": "creative-018", "category": "creative", "text": "Originality is undetected influence.", "source": "Mark Twain (commonly attributed)"},
    {"id": "creative-019", "category": "creative", "text": "Notebooks live longer than ideas. Carry one.", "source": "Craft practice"},
    {"id": "creative-020", "category": "creative", "text": "Constraints are creativity's friend. Set artificial limits to provoke moves.", "source": "Creative constraint"},
    {"id": "creative-021", "category": "creative", "text": "Volume produces taste. Make 100 of anything to know what good looks like.", "source": "Volume principle"},
    {"id": "creative-022", "category": "creative", "text": "Two hours of focused creative work beats six hours of distracted creative work every time.", "source": "Deep work / craft"},
    {"id": "creative-023", "category": "creative", "text": "The blank page is just feedback waiting to happen. Fill it.", "source": "Iteration principle"},
    {"id": "creative-024", "category": "creative", "text": "Steal like an artist; make it yours; sign it.", "source": "Austin Kleon"},
    {"id": "creative-025", "category": "creative", "text": "Show your work. Documentation is a creative act in itself.", "source": "Austin Kleon"},
    {"id": "creative-026", "category": "creative", "text": "Edit ruthlessly. The work is half what you keep and half what you cut.", "source": "Craft principle"},
    {"id": "creative-027", "category": "creative", "text": "Make peace with the fact that the first 90% takes 90% of the time, and the last 10% takes the other 90%.", "source": "Craft folklore"},
    {"id": "creative-028", "category": "creative", "text": "Publishing is finishing. Finish more often.", "source": "Iteration principle"},
    {"id": "creative-029", "category": "creative", "text": "Don't compare your behind-the-scenes to someone else's highlight reel.", "source": "Creative compassion"},
    {"id": "creative-030", "category": "creative", "text": "Make today's thing today. Today's thing tomorrow is twice as hard.", "source": "Compounding principle"},
    {"id": "creative-031", "category": "creative", "text": "The artist who waits for permission to make art is the artist who doesn't.", "source": "Creative principle"},
    {"id": "creative-032", "category": "creative", "text": "Lower the cost of starting. Higher the cost of stopping. That's craftsmanship.", "source": "Craft principle"},
    {"id": "creative-033", "category": "creative", "text": "Most great art comes from boredom, not stimulation.", "source": "Deep work principle"},
    {"id": "creative-034", "category": "creative", "text": "The work is the practice and the practice is the work.", "source": "Zen-aligned craft"},
    {"id": "creative-035", "category": "creative", "text": "Be patient with the process. Be impatient with your effort.", "source": "Discipline principle"},
]


def all_extension_entries() -> list[dict]:
    return (
        list(_STOIC_V3) + list(_GROWTH_V3) + list(_FINANCIAL_V3) +
        list(_PERSONAL_V3) + list(_CBT_V3) + list(_OPS_V3) + list(_CREATIVE_V3)
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
        log.info("[wisdom_corpus_v3] appended %d entries -> %s", added, wisdom_file)
    return added


__all__ = ["all_extension_entries", "extend_wisdom_corpus"]
