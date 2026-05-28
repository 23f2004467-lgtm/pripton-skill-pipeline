# On Becoming a Software Engineer

I've been thinking lately about what it actually means to grow as an engineer.
Not in the resume sense — title progression, salary bands, the conventional
markers — but in the sense of becoming someone who reaches for the right tool,
makes the right call under pressure, and ages well in this profession.

When I started out, I thought the job was about knowing things. The more
frameworks I'd touched, the more languages I could list, the better I'd be.
I spent my first two years collecting tools. I wrote a side project in every
framework I heard about. I learned five different deployment systems before I'd
shipped anything meaningful in any of them. The thing nobody told me was that
knowing about things and being good at things are not the same skill, and that
the second one is much harder than the first.

The shift happened slowly. I'd be on call and an alert would fire and I'd
realize I had absolutely no idea what was actually happening — I'd configured
the alert from a template, I'd never looked at the underlying metric, I didn't
know the system well enough to even have a hypothesis. That was a humbling few
months. I'd been writing code for years but I hadn't been building intuition.

Intuition is the thing I now think about most. The senior engineers I admire
all share a kind of intellectual patience. They don't rush to a solution. They
sit with the problem until they understand it. They ask annoying questions
like "what do we know is actually true here?" and "what's the simplest thing
that could explain this?" When they finally suggest a fix, it's usually
disappointingly small — a single line, a single config change — but it works
the first time. That patience is built from running into the same shape of
problem dozens of times across years, and starting to see the pattern under
the surface.

The other thing I've started to notice is how much the job is actually about
communication, not code. I used to think of meetings and documentation and
code reviews as overhead on top of the real work. Now I think they are the
real work. Code is just the artifact that records what we decided. The
deciding is the part that matters, and deciding well requires understanding
the actual problem, the actual constraints, the actual humans involved.

When you write a long technical document, what you're really doing is
forcing yourself to think clearly. The doc is a side effect. The thinking
is the point. The best documents I've ever read were written by people who
didn't fully understand the problem when they started, and who used the
writing to figure it out. You can feel it in the prose — there's a moment
midway through where the author realizes something, and the rest of the doc
is a different document than the first half.

I want to talk for a moment about the relationship between speed and quality,
because I think the conventional wisdom is wrong. The idea that you trade
off speed for quality is true at small scales — yes, taking more time to
polish a single function makes it better. But at the level of weeks and
months and years, the trade-off inverts. The fastest engineers I know are
also the most careful. They move fast because they don't make the kind of
mistakes that require rework. They write code that doesn't break the build,
that doesn't need to be rewritten in three months, that doesn't require an
incident response at 2am. The slow engineers are the ones who think speed
means typing fast. They produce work that has to be redone, which is the
slowest possible mode.

A lot of what I now consider craft is restraint. Not adding the abstraction.
Not introducing the framework. Not optimizing prematurely. The discipline of
solving exactly the problem in front of you, in the simplest way that could
possibly work, is rarer than it sounds. Most engineering codebases I've seen
are heavy with code written for problems that never materialized — flexibility
that wasn't needed, configurability that nobody uses, plugin systems with one
plugin. Each of those decisions felt smart at the time. In aggregate they
make the codebase impossible to change.

I've been thinking about what advice I'd give my younger self. The honest
answer is that the advice probably wouldn't have helped — most of this stuff
has to be learned by collision with reality, not by being told. But the
attempted answer is something like: focus on understanding one system deeply
rather than touching twenty systems shallowly. Read the source code of the
tools you use. Write code that someone else has to maintain, and pay
attention to which decisions hurt them. When you're stuck, write down what
you know and what you don't know in plain prose before you write any more
code. And be suspicious of any pattern you reach for that has a fancy name.
Most of them are wrong for your situation.

I'm not at the end of any of this, of course. The further I go, the more I
notice how much I still don't know. The people whose work I most admire seem
to have a healthier relationship with that fact than I do. They're curious
without being anxious about it. They learn things because the things are
interesting, not because they're trying to outrun a feeling of inadequacy.
That's the next thing to internalize, I think — the difference between
learning out of curiosity and learning out of fear. The first one is
sustainable. The second one eats you.

So that's where my head is. Some of this will probably look naive to me in
five years. That's fine. The whole point of writing things down is to be
able to look back and notice what you got wrong. I'd rather get the chance
to be embarrassed by my past self than be too cautious to ever commit to a
position. That's its own kind of trap.
