# See the documentation for the finworks-production-get-snippets.sh script for
# more details.

# Models
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://training.aospartner.com/api/modelmanager/model-portfolios" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.key" \
     -o model-portfolios.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"

# Instruments
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://training.aospartner.com/api/modelmanager/instruments" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.key" \
     -o instruments.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"

# Investors
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://training.aospartner.com/api/modelmanager/investors" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.key" \
     -o investors.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"

# Holdings on date 2024-12-09
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://training.aospartner.com/api/modelmanager/holdings?date=2024-12-09" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.key" \
     -o holdings.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"

# Transactions on date 2024-12-09
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://training.aospartner.com/api/modelmanager/transactions?date=2024-12-09" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/training.aospartner.com/cert.key" \
     -o transactions.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"
