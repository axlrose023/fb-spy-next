TEXT_SCOPE = """\
Classify whether this Facebook ad belongs to a narrow grey/scam finance buyer-funnel watchlist.

This is NOT a general finance or general scam classifier, nor a broad crypto,
forex, broker, investing, health, gambling, dating, or e-commerce classifier.
Mark RELEVANT only when the ad fits
one of these target classes AND has clear grey/scam media-buyer funnel signals:
1. Visible finance-scam offer: crypto, forex, trading, investing, yield, broker deposits, signal groups, copy-trading, passive income from a financial/investment system, payouts from an investment/trading system, or a vague high-return money system with explicit financial/profit/deposit/payout amounts or finance context.
2. Hidden-offer fake-news prelander: a sensational news/TV/current-affairs/public-figure story that is very likely a paid social prelander for a finance/crypto/investment scam funnel even when the final offer is hidden behind the click.

Important hidden-offer prelander rule:
- Mark RELEVANT even when the first Facebook card does not visibly mention crypto, trading, or investing if it combines BOTH:
  a) fake-news/public-figure bait: politicians, ministers, presidents, TV presenters, journalists, celebrities, bank/state figures, parliament, police/court/arrest scenes, "breaking news", live-broadcast scandal, "microphone left on", "truth revealed", "country shocked", leaked/secret information, corruption, public money, bank/economic scandal, or similar sensational current-affairs bait; AND
  b) performance-funnel/grey signals: suspicious redirect/tracking/affiliate/autologin URL, throwaway or mismatched domain, Facebook campaign parameters, ad_id/pixel/token parameters, registration/lead-gen CTA, fake video-play creative, or advertiser/domain/brand mismatch.
- These fake-news public-figure prelanders are a primary target class because finance scam buyers often hide the crypto/trading/investment offer until after the click.
- Generalize from Turkish and Czech examples: Turkish "KAYIT" ads with TL amounts, banks, politicians, parliament, or "microphone/scandal" hooks; Czech fake ČT/news-style ads about politicians, prime ministers, ministers, prison/arrest, "unique information", or "truth revealed" on random domains.
- Generalize from Philippine examples: fake or repurposed GMA Network/Fast Talk/news-show creatives with a governor, mayor, BSP/central-bank official, TV host, business leader, staged scandal or medical emergency; and fake Caticlan/local-government app creatives using a public/business figure plus "click the link below." Treat these as suspected hidden finance prelanders only when they also have a random/mismatched domain, app/registration CTA, tracking, advertiser mismatch, or similar performance-funnel evidence.
- Do NOT treat a random domain, Facebook tracking parameters, a generic "register/learn more" CTA, or an ordinary person talking in a video as enough evidence by itself. The ad still needs a strong target anchor: finance/profit/bank/state/official/public-figure/fake-news scandal/police/arrest/parliament/TV-news evidence.

Grey/scam signals include:
- fake-news or advertorial style, "breaking news", "everyone is talking", scandal/confession stories, or public-figure/celebrity bait
- impersonation or suspicious use of banks, state programs, politicians, famous people, or large brands
- promises of payments, monthly income, fast profit, guaranteed/simple earnings, passive income, financial freedom, or unusually high returns
- AI/algorithmic/automated/quantum trading bot funnels that push registration, deposit, or profit chasing
- vague lead-gen pages, quiz/registration funnels, affiliate/autologin URLs, suspicious redirects, throwaway domains, or mismatched advertiser/domain/brand
- clickbait that pushes consumers into an unregulated investment, crypto, trading, or money-making flow

Generic make-money clarification:
- Do NOT mark an ad relevant only because it promises money, online income, business growth, AI income, entrepreneurship income, webinar income, or a guide to earning online. It must be specifically tied to finance, investing, crypto, forex, trading, yield, signal groups, broker deposits, copy-trading, or match the fake-news finance prelander exception.

Mark NOT RELEVANT for:
- normal political/news/media ads from credible or consistent publishers when there is no suspicious redirect, throwaway lead-gen domain, registration funnel, public-figure scam framing, or hidden finance-scam prelander pattern
- ordinary UGC, street-interview, selfie, lifestyle, emotional TV clips, or generic "method/easy start/three months/register now" ads when the visible creative and metadata do not show finance, investing, crypto, trading, bank/state/public-figure bait, or a fake-news scandal/current-affairs prelander
- legitimate or regulated-looking brokers, prop firms, crypto exchanges, banks, funds, portfolio managers, market-data apps, or trading education when there is no clear grey/scam signal
- prop/funded account challenge promos, discount codes, BOGO offers, refundable challenge fees, "get funded" ads, or demo-account reward ads unless they also use fake-news/public-figure bait, guaranteed profit, deceptive impersonation, or suspicious scam prelander tactics
- stock-picking apps, portfolio research tools, market-data apps, or newsletter-style "stock pick" ads when they look like a normal branded app/service and do not use fake-news impersonation, throwaway lead-gen pages, Telegram/signal funnels, or unrealistic guaranteed-return claims
- normal broker commodity/gold/forex ads, including "trade gold/oil/forex" CTAs, if they are broker-brand ads without fake-news, public-figure bait, suspicious redirects, or exaggerated profit promises
- normal branded broker, CFD, prop-firm, funded-account, or trading-platform promotions when the advertiser and destination are the same brand and there is no fake-news impersonation, hidden prelander, or guaranteed-return scam claim; discounts, daily payouts, profit splits, challenge refunds, leverage, sports giveaways, and celebrity-branded prizes alone are not enough
- corporate technology, cloud-partner, developer-skilling, certification, enterprise-software, or Microsoft partner-program ads, even when they discuss business revenue or link to a campaign microsite
- video-game stores, virtual items, in-game currency, game "bonds", balance top-ups, refunds, or gaming rewards; financial words used only inside a game are not finance-scam evidence
- legitimate payment-app campaigns that use known mobile attribution/deep-link domains; an attribution hostname alone is not brand impersonation or a suspicious redirect
- ordinary banking, insurance, payments, employee benefits, cards, payroll, accounting, ERP, tax, B2B SaaS
- generic business consulting, CIO/IT services, marketing agencies, analytics, competitor intelligence
- generic AI/business/webinar/make-money-online courses or guides when they are not specifically finance, investing, crypto, forex, trading, yield, signals, or a fake-news finance prelander
- hotels, travel, cars, telecom, cosmetics, retail, food, furniture, pet products, music, education, jobs
- health/nutra/medical products and funnels, including fake medical advertorials, hospital/doctor/news impersonation, miracle cures, disease-reversal claims, or fear-based medical creatives, unless the same funnel explicitly reveals a finance/investment offer
- pure casino/gambling/sports betting, betting bonuses, trial bonuses, "win money" offers, or casino deposit/payout claims unless they clearly include crypto/investment/trading/yield scam messaging
- dating/chat acquisition, including AI/stock-person creatives, unless the same funnel explicitly reveals a finance/investment offer
- generic e-commerce, turnkey-business, coaching, or entrepreneurship offers without a specific finance/investment target
- ordinary branded forex/trading education, courses, academies, seminars, or market-learning communities when they only promise learning, opportunity, or financial freedom and have no fake-news/public-figure impersonation, guaranteed or exaggerated returns, hidden investment platform, suspicious domain, or similar scam evidence
- trading ebooks, lessons, workshops, and educational guides when they sell training or content rather than a deceptive investment/deposit funnel
- normal investment funds or corporate capital firms if the pitch is B2B/institutional or brand-building rather than a scammy consumer funnel

Be very strict. The default is NOT RELEVANT.
Do NOT mark an ad relevant only because it mentions forex, crypto, trading, investment, broker, capital, CIO, benefits, insurance, finance, money, online income, AI income, casino winnings, or betting payouts.
Do NOT mark an ad relevant only because it uses a throwaway domain, Facebook campaign parameters, ad_id/pixel parameters, affiliate-style tracking, or a registration CTA; those are supporting signals, not the target class.
If the ad looks like a normal financial service, reject it even if users can trade or invest there.
If the ad is health/nutra/medical, reject it even when it is deceptive, impersonates a hospital/news outlet/public figure, or makes miracle claims, unless a finance/investment offer is also evidenced.
If the ad is only gambling/casino/betting, reject it even if it promises income, winnings, bonuses, deposits, or payouts.
If the ad is a generic AI, entrepreneurship, webinar, or online-income offer, reject it even if it promises a large monthly income, unless it is specifically a financial/crypto/trading/yield offer or a fake-news finance prelander.
Do NOT reject fake-news public-figure prelanders just because the final investment/crypto/trading offer is not visible in the first Facebook card; if they match the hidden-offer prelander rule above, mark them relevant.
"""
