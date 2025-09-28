const express = require('express');
const multer = require('multer');
const { parse } = require('csv-parse/sync');
const fs = require('fs');
const Web3 = require('web3').default;
const CertificateChain = require('./build/contracts/CertificateChain.json');
const path = require('path');
const crypto = require('crypto');

const app = express();
const upload = multer({ dest: 'uploads/' });

// Connect to Ganache
const web3 = new Web3('http://localhost:7545');

// ✅ Automatically load latest deployed contract address
let contractAddress;
try {
const networkId = Object.keys(CertificateChain.networks)[0]; // e.g. "5777"
contractAddress = CertificateChain.networks[networkId].address;
console.log(`✅ Using contract address from build file: ${contractAddress}`);
} catch (err) {
console.error("❌ No deployed contract found in build file. Did you run `truffle migrate --reset`?");
process.exit(1);
}

const contract = new web3.eth.Contract(CertificateChain.abi, contractAddress);

app.use(express.json());
app.use(express.static('public')); // Serve frontend files

// Serve upload page
app.get('/', (req, res) => {
res.sendFile(path.join(__dirname, 'public', 'uni_dashboard.html'));
});

app.get('/uni_upload', (req, res) => {
res.sendFile(path.join(__dirname, 'public', 'uni_upload.html'));
});

app.get('/verify', (req, res) => {
res.sendFile(path.join(__dirname, 'public', 'verify.html'));
});

// ✅ API Endpoint to Upload CSV and Store in System
app.post('/api/upload-certificates', upload.single('csvFile'), async (req, res) => {
try {
if (!req.file) {
return res.status(400).json({ error: 'No file uploaded' });
}

// 1. Read and parse CSV
const fileContent = fs.readFileSync(req.file.path);
const records = parse(fileContent, { columns: true });

// 2. Generate hashes
function stableStringify(obj) {
return JSON.stringify(Object.keys(obj).sort().reduce((acc, key) => {
acc[key] = obj[key];
return acc;
}, {}));
}

const hashes = records.map(row =>
crypto.createHash("sha256").update(stableStringify(row)).digest("hex")
);

console.log("Generated hashes:", hashes);

// 3. Get accounts from Ganache
const accounts = await web3.eth.getAccounts();

// 4. Estimate gas first
const gasEstimate = await contract.methods.addBatch(hashes).estimateGas({
from: accounts[0]
});
const gasEstimateNum = Number(gasEstimate);
console.log("Gas estimate:", gasEstimate);

// 5. Send transaction with estimated gas + buffer
const tx = await contract.methods.addBatch(hashes).send({
from: accounts[0],
gas: Math.floor(gasEstimateNum * 1.2), // 20% buffer
gasPrice: web3.utils.toWei('20', 'gwei')
});

// 6. Clean up uploaded file
fs.unlinkSync(req.file.path);

res.json({
success: true,
transactionHash: tx.transactionHash,
hashesCount: hashes.length,
gasUsed: tx.gasUsed.toString(),
message: `Successfully uploaded ${hashes.length} certificates to system`
});

} catch (error) {
console.error('Error:', error);
res.status(500).json({ error: error.message });
}
});

// ✅ API Endpoint to Verify Certificate
app.post('/api/verify-certificate', async (req, res) => {
try {
const { rollNo, name, course, branch, grade, year } = req.body;

// Generate hash (same logic as before)
function stableStringify(obj) {
return JSON.stringify(Object.keys(obj).sort().reduce((acc, key) => {
acc[key] = obj[key];
return acc;
}, {}));
}

const studentData = { "Roll No": rollNo, "Name": name, "Course": course, "Branch": branch, "Grade": grade, "Year": year };
const candidateHash = crypto.createHash("sha256").update(stableStringify(studentData)).digest("hex");

// Verify on blockchain
const result = await contract.methods.verifyCertificate(candidateHash).call();

res.json({
isValid: result[0],
timestamp: result[1].toString(),
issuer: result[2],
candidateHash: candidateHash
});

} catch (error) {
res.status(500).json({ error: error.message });
}
});

// ✅ Get contract info
app.get('/api/contract-info', async (req, res) => {
try {
const accounts = await web3.eth.getAccounts();
res.json({
contractAddress: contractAddress,
connectedAccount: accounts[0],
networkId: await web3.eth.net.getId().toString()
});
} catch (error) {
res.status(500).json({ error: error.message });
}
});

const PORT = 3000;
app.listen(PORT, () => {
console.log(`🚀 Backend server running on http://localhost:${PORT}`);
console.log(`📂 Upload page: http://localhost:${PORT}/upload`);
console.log(`🔍 Verify page: http://localhost:${PORT}/verify`);
});