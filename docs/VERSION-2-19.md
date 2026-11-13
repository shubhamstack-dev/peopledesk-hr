# PeopleDesk 2.19: the candidate portal, and mail with candidates both ways

## Updating the server

Apply the patch or use the zip, then rebuild as usual. There are no new packages, tables or migrations: the
conversation is kept on the candidate record, and the issued offer letter on the offer.

**To receive replies by e-mail**, the group administrator sets up the replies mailbox under **Settings › Replies from
candidates**: a mailbox for this alone (for example *careers-replies@company.in*) with IMAP access.

- **Password sign-in:** any mail service with IMAP.
- **Microsoft 365:** uses the same Entra app as sending. Give that app the Exchange permission **IMAP.AccessAsApp**,
  and grant it the mailbox in Exchange.

**Read the mailbox now** checks it at once. Without the replies mailbox, everything else works: replies are made in
the portal, and e-mails to candidates ask them to reply there.

## The candidate's portal

A candidate signs in with the candidate sign-in they created from HR's link (2.17), from that link or from the
sign-in page (*Candidate? Sign in*). There are three tabs.

### My applications

Each job the candidate is in, with where it stands, as steps: *Application review*, *Interviews*, *Selection*,
*Offer* and *Joining*. The status is in plain words:

- Under review
- Interview scheduled, with the next round and time
- Interviews done
- Selected (the offer is being prepared)
- Offer made
- Offer accepted
- Joined
- Not selected
- Closed

Management approval of the shortlist, panel feedback, HR's notes and the final selection's discussion are never
shown to the candidate.

**Interviews:** round, date and time, length, how it happens (video with **Join the call**, in person with the
venue, or by phone), the panel's names, and whether it is scheduled, done, cancelled or missed. **Add to calendar**
downloads the interview as a calendar file.

### The offer

The offer appears once HR issues it.

- **The letter:** exactly as issued, kept on the offer at that moment. It is shown read-only in the page and can be
  downloaded.
- **The terms:** CTC, joining date, joining bonus, reply-by date and letter number. A revised offer shows its round.

The candidate can respond in three ways, and each takes effect at once:

- **Accept the offer.** The typed full name is the signature, and must match the name on the letter. The candidate
  ticks that they accept and may attach a signed scan. The application moves to *Offer accepted*, a follow-up is set
  to confirm the joining date, and HR is told. The signature, its time and the address it came from are kept.
- **Ask for changes.** The candidate can ask for a different CTC, joining date or joining bonus, or anything else
  (notice buyout, relocation, designation), with a reason. This becomes a negotiation round (2.14) marked *asked in
  the candidate portal*. HR answers it, and the answer reaches the candidate. Only one request can be open at a time;
  the offer as issued stays open meanwhile.
- **Decline**, with a reason. HR is told and chooses the next step.

An offer that is past its reply-by date, or replaced by a newer letter, cannot be answered: the candidate is asked to
write to HR.

### Messages

The conversation with HR. The candidate writes here (with attachments: PDF, photos or Word, up to 5 MB each, up to 5)
and can also reply to HR's e-mails by e-mail.

### My details

The details form, as before.

## HR's side

### Messages on the application page

The **Messages with …** card shows the whole conversation: who wrote, when, and whether in PeopleDesk, the portal, by
e-mail, or as a notice. It also shows whether the candidate has read HR's messages.

**Write to the candidate** sends a message with a subject, the text and attachments. It appears in their portal and
is e-mailed to them. Ready texts are available:

- Please confirm the interview time
- Documents for joining
- Please complete your details
- Not selected

HR and the requisition's hiring manager and raiser can write to the candidate. Outside HR, other employees do not
receive the conversation at all.

A message from the candidate is e-mailed to the person who handles the thread: the last person to write to the
candidate, else who sent the form link, else who added the candidate. It also appears in their **Approvals** until
the application page is opened.

### Notices

Notices go to the candidate by themselves, in the portal and by e-mail:

- **Interview scheduled, moved or cancelled:** after HR schedules or updates an interview, with the time, the link,
  venue or phone, and the panel.
- **Offer issued:** with a pointer to the portal. A revised offer says so.
- **HR's answer to the candidate's request.**

Each notice is sent once.

### Answering a request for changes

The negotiation card shows **Answer the candidate** on a request made in the portal.

- **Agree:** give the agreed CTC, joining date or bonus. Then **Revise the offer to the agreed terms**: it goes for
  approval again, and the candidate gets the new letter in their portal.
- **Keep the offer as it is.**

The answer is sent to the candidate either way. Approvals shows *Asked for changes to the offer* until it is
answered.

### After an online decline

The application stays in *Offered*, and the offer rounds card shows the candidate's reason with two choices:

- **Make a revised offer:** a new round. The edit form opens; the new offer is approved and issued as usual.
- **Close: not joining:** the application moves to Rejected.

Approvals shows it too.

### The issued offer letter

When HR issues an offer, the letter is printed as before and also kept on the offer for the candidate's portal. Offers
issued before this version have no stored letter: the portal shows the terms and asks the candidate to request a copy.

## E-mail both ways

- **What is e-mailed:** every message to the candidate (from HR, or a notice) and every message from the candidate to
  HR.
- **The reference:** each e-mail has the thread's reference in the subject, *[Ref: PD-XXXXXXXX]*. With the replies
  mailbox on, Reply-To points to it.
- **Reading replies:** the server reads the replies mailbox every two minutes. A new e-mail with a reference is added
  to that candidate's thread:
  - **From the candidate's address:** a message from the candidate, passed on to HR.
  - **From an employee who may write to the candidate** (HR of the company, the thread's owner, the hiring manager or
    raiser of one of the candidate's requisitions): a message to the candidate, passed on to them. So HR can simply
    reply to the e-mail PeopleDesk sent them.
  - **Anything else** (other senders, automatic replies and out-of-office, our own e-mails): left out, and other
    senders are noted in the audit log.
- **Cleaning up replies:** the quoted earlier e-mail under a reply (Gmail, Outlook and phone footers) is cut off.
  Attachments (PDF, photos, Word, up to 5 MB, up to 5) are kept. Each e-mail is read once and marked read in the
  mailbox.
- **Editable templates**, under **E-mail templates**:
  - *To a candidate:* the wrapper for every message to a candidate;
  - *From a candidate:* the wrapper for every message from a candidate to HR;
  - *Interview notice*;
  - *Offer notice*.

## For administrators

**New fields:**

- Candidates: `msgs` (the thread), `msgRef` (the reference) and `msgOwner` (who handles it). These are written only on
  the server, a save from the app keeps them as stored, and they are removed for everyone outside HR.
- Offers: `letterHtml`, `respondedVia: "portal"`, and `signed.esign` (name, time, address).
- Negotiation rounds: `viaPortal`, plus HR's `answer`, `answeredBy` and `answeredAt`.
- Interviews: `candNotice`.

**What the candidate did stands:** a save from the app with an older copy of the application (offer still *issued*,
no candidate round) keeps the candidate's acceptance, decline and requests, and the notes and history the server
added (`cportal.merge_app`). An online acceptance's typed signature counts as the signed copy for the 2.18 rule.

**New modules:**

- `backend/app/cportal.py`: what the candidate sees and does, and the thread.
- `backend/app/cmail.py`: e-mail both ways, and the replies mailbox reader.
- `frontend/src/pages/CandidatePortal.jsx`.

**New endpoints:**

- Candidate: `/api/candidate/portal`, `/api/candidate/offer`, `/api/candidate/message`, `/api/candidate/messages/read`
  and `/api/candidate/files/{id}`. A candidate opens only files in their own messages and their own signed letter.
- HR: `/api/recruit/message`, `/api/recruit/messages/read` and `/api/recruit/candnotify`.
- Administrator: `/api/admin/mailin` and `/api/admin/mailin/check`.

**Mail sending** (`mailer.send`) takes a Reply-To.

**Tests:** `backend/tests/test_candidate_portal.py` (no database needed) covers:

- statuses and steps;
- what the candidate never sees;
- accept, decline and ask-for-changes rules;
- the thread and its references;
- stale saves;
- cutting quoted text, attachments, and automatic replies.
