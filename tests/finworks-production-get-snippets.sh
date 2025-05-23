# Description: This low level bash script uses the curl GET method to test the
# Finworks production API endpoints. The response times are printed to the
# console and any received JSON data is saved to a file. The script uses the
# client certificate and key to authenticate the requests. The script is
# designed to be run from the command line.
#
# Usage: run the script from the command line. Ensure that curl is installed and
# the client certificate and key are in the specified directory. The script
# will create the output files in the current directory. You may need to modify
# the script to change the output directory or the certificate and key paths.
#
# Example:
#   cd to the directory where the script is located
#   > chmod +x finworks-production-get-snippets.sh
#   > ./finworks-production-get-snippets.sh
#   or
#   > bash finworks-production-get-snippets.sh
#   or
#   > sh finworks-production-get-snippets.sh



# Models
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://secure.aospartner.com/api/modelmanager/model-portfolios" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.key" \
     -o model-portfolios.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"

# Instruments
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://secure.aospartner.com/api/modelmanager/instruments" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.key" \
     -o instruments.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"

# Investors
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://secure.aospartner.com/api/modelmanager/investors" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.key" \
     -o investors.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"

# Holdings on date 2024-12-09
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://secure.aospartner.com/api/modelmanager/holdings?date=2024-12-09" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.key" \
     -o holdings.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"

# Transactions on date 2024-12-09
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" && \
time curl -X GET "https://secure.aospartner.com/api/modelmanager/transactions?date=2024-12-09" \
     -H "Authorization: Bearer QyT7oTnIvmiq5swQ"\
     -H "Content-Type: application/json" \
     --cert "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.crt" \
     --key "/home/justin/Documents/Develop/fundmanage/src/fundmanage/certificates/secure.aospartner.com/cert.key" \
     -o transactions.json \
     --trace-time \
     -w "\n\nTotal time: %{time_total}s\nName lookup time: %{time_namelookup}s\nConnect time: %{time_connect}s\nApp connect time: %{time_appconnect}s\nPre-transfer time: %{time_pretransfer}s\nStart-transfer time: %{time_starttransfer}s\nRedirect time: %{time_redirect}s\n\n"
