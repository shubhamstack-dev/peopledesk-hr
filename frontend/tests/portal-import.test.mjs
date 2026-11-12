// node frontend/tests/portal-import.test.mjs
import assert from 'node:assert/strict';
import { parseExp, parseCtc, parseNotice, parsePhone, findHeaderRow, autoMap, rowToCand, matchCvFile } from '../src/engine/portal-import.js';

assert.equal(parseExp('5 Yrs 3 Months'), 5.3); assert.equal(parseExp('5y 6m'), 5.5); assert.equal(parseExp('Fresher'), 0);
assert.equal(parseExp('60 months'), 5); assert.equal(parseExp('7'), 7); assert.equal(parseExp('5 Year(s) 0 Month(s)'), 5); assert.equal(parseExp(''), '');
assert.equal(parseCtc('12 Lacs'), 1200000); assert.equal(parseCtc('12.5 LPA'), 1250000); assert.equal(parseCtc('Rs. 12 Lacs 50 Thousand'), 1250000);
assert.equal(parseCtc('INR 12,00,000'), 1200000); assert.equal(parseCtc('1.2 Cr'), 12000000); assert.equal(parseCtc('50,000 per month'), 600000);
assert.equal(parseCtc('8'), 800000); assert.equal(parseCtc('10 - 12 Lacs'), 1000000); assert.equal(parseCtc('Not disclosed'), ''); assert.equal(parseCtc('₹ 9,50,000'), 950000);
assert.equal(parseNotice('Immediate'), 0); assert.equal(parseNotice('15 Days or less'), 15); assert.equal(parseNotice('1 Month'), 30);
assert.equal(parseNotice('3 Months'), 90); assert.equal(parseNotice('More than 3 Months'), 120); assert.equal(parseNotice('Serving Notice Period'), 0); assert.equal(parseNotice('60'), 60);
assert.equal(parsePhone('+91 98765 43210'), '9876543210'); assert.equal(parsePhone('09876543210'), '9876543210'); assert.equal(parsePhone('9876543210, 9123456789'), '9876543210');

const rows = [['Naukri RMS export'], [], ['Name', 'Email ID', 'Phone Number', 'Total Experience', 'Current Company', 'Current Designation', 'Current Location', 'Annual Salary', 'Expected CTC', 'Notice Period', 'Key Skills'],
  ['Rohit Verma', 'Rohit.V@mail.com', '+91-9876543210', '5 Yrs 3 Months', 'Acme', 'Sales Officer', 'Pune, Maharashtra', '6.5 Lacs', '8 Lacs', '1 Month', 'B2B Sales | CRM']];
const h = findHeaderRow(rows); assert.equal(h, 2);
const map = autoMap(rows[h]);
assert.equal(map.name, 0); assert.equal(map.email, 1); assert.equal(map.phone, 2); assert.equal(map.expYears, 3); assert.equal(map.currentCompany, 4);
assert.equal(map.currentTitle, 5); assert.equal(map.location, 6); assert.equal(map.currentCtc, 7); assert.equal(map.expectedCtc, 8); assert.equal(map.noticeDays, 9); assert.equal(map.skills, 10);
const c = rowToCand(rows[3], map);
assert.deepEqual([c.name, c.email, c.phone, c.expYears, c.location, c.currentCtc, c.expectedCtc, c.noticeDays, c.skills], ['Rohit Verma', 'rohit.v@mail.com', '9876543210', 5.3, 'Pune', 650000, 800000, 30, 'B2B Sales, CRM']);

const li = autoMap(['First Name', 'Last Name', 'Headline', 'Email Address', 'Location']);
const c2 = rowToCand(['Meera', 'Iyer', 'Marketing Lead', 'meera@x.in', 'Bengaluru'], li);
assert.equal(c2.name, 'Meera Iyer'); assert.equal(c2.currentTitle, 'Marketing Lead');

const cs = [{ name: 'Rohit Verma', email: 'rohit.v@mail.com', phone: '9876543210' }, { name: 'Meera Iyer', email: '', phone: '' }, { name: 'Rohit Sharma', email: '', phone: '' }];
assert.equal(matchCvFile('Naukri_RohitVerma[5y_3m].pdf', cs), 0); assert.equal(matchCvFile('CV 9876543210.docx', cs), 0);
assert.equal(matchCvFile('meera-iyer-resume.pdf', cs), 1); assert.equal(matchCvFile('Rohit.pdf', cs), -1); assert.equal(matchCvFile('unknown.pdf', cs), -1);
console.log('portal-import: all checks passed');
