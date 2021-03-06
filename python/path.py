import gmplot
from glob import glob
import urllib2
import json
import scrapetimetable
import datetime
import tables
import math
from scipy import optimize
import scipy.io as io
import matplotlib.pyplot as plt
import numpy as np
plt.style.use('ggplot')

# Paramaterizes the path of the 1 bus
path_lats = [42.373989, 42.373203, 42.375638, 42.375908, 42.375576, 42.374745, 42.372336, 42.372210, 42.371048, 42.368632, 42.360855, 42.359038, 42.343444, 42.340393, 42.333535, 42.331213, 42.332889, 42.331979, 42.330677, 42.330037]
path_lons = [-71.118910, -71.118116, -71.118449, -71.117848, -71.115702, -71.114484, -71.115128, -71.115643,-71.116074, -71.109294, -71.096016, -71.093586, -71.085840, -71.081463, -71.073351, -71.076999, -71.081076, -71.081699, -71.083244, -71.084317]

boston_lat = 42.3528
boston_lon = -71.1048
boston_x = 1092798.35753
boston_y = 2698296.888

n = len(path_lats)

# path = get_path()
# total_distance = get_total_distance(path[0],path[1])
total_distance = 485.391855184

def get_total_distance(xs,ys):
    d = 0
    for i in range(len(xs)-1):
        x1,x2 = xs[i],xs[i+1]
        y1,y2 = ys[i],ys[i+1]
        d += np.linalg.norm((x2-x1,y2-y1))
    return d

def plot_map(lats,lons):
    gmap = gmplot.GoogleMapPlotter(boston_lat, boston_lon, 14)
    gmap.scatter(lats, lons, '#3B0B39', size=40, marker=False)
    gmap.draw("mymap.html")

# Convert to a reasonable x,y paramaterization
def gps_to_xy(lats,lons):
    # radius of earth, pretty rough though
    R = 6371
    xs = [-R*lon*math.cos(path_lats[0]*180/math.pi)-boston_y for lon in lons]
    ys = [R*lat-boston_y for lat in lats]
    return xs,ys

def get_path():
    return gps_to_xy(path_lats,path_lons)

# Takes in a point (x,y) and a set of points (xs,ys) which create a piecewise linear path
# Then projects the point onto the closest linear section of that path
def project(x,y,xs,ys,total_distance):
    smallest_d = "Taylor"
    point = None
    cum_distance = 0
    percentage = 0
    best_proj = 0
    for i in range(len(xs)-1):
        x1,x2 = xs[i],xs[i+1]
        y1,y2 = ys[i],ys[i+1]
        c,p = closest_point((x1,y1),(x2,y2),(x,y))
        d = np.linalg.norm(np.subtract(c,(x,y)))
        if d < smallest_d:
            smallest_d = d
            best_proj = p
            if p< 0 :
                p = 0
            percentage = (cum_distance + p) / total_distance
            point = c
        cum_distance += np.linalg.norm((x2-x1,y2-y1))
    return point,percentage

# https://stackoverflow.com/questions/3749512/python-group-by
def group_by(seqs,idx=0,merge=True):
    d = dict()
    for seq in seqs:
        k = seq[idx]
        v = d.get(k,tuple()) + (seq[:idx]+seq[idx+1:] if merge else (seq[:idx]+seq[idx+1:],))
        d.update({k:v})
    return d

# Returns the closest point as well as the distance along the path
def closest_point(a, b, p):
    a_to_p = np.subtract(p,a)
    a_to_b = np.subtract(b,a)
    proj = np.dot(a_to_p,a_to_b)/np.linalg.norm(a_to_b)
    return np.add(a,proj*a_to_b/np.linalg.norm(a_to_b)), proj

# Takes in a filename and then returns the (xs,ys,ts) for each bus in a dictionary
def get_trajectory(filename):
    route = 1
    direction = '1_1_var0'
    h5file = tables.open_file(filename)
    VehicleLocations = h5file.root.VehicleLocations
    queryString = "((route == '%s') & (direction == '%s'))" % (route, direction)
    trajectories = VehicleLocations.where(queryString)
    queryResults = [(timePoint['time'], timePoint['vehicleID'], timePoint['latitude'], timePoint['longitude']) for timePoint in trajectories]
    d = group_by(queryResults,1,False)
    # Tuples of (time,lat,lon)
    bus_to_trajectory = {}
    for vehicleID in d:
        d[vehicleID] = sorted(d[vehicleID],key=lambda x:x[0])
        lats = [x[1] for x in d[vehicleID]]
        lons = [x[2] for x in d[vehicleID]]
        ts = [x[0] for x in d[vehicleID]]
        xs,ys = gps_to_xy(lats,lons)
        bus_to_trajectory[vehicleID] = (xs,ys,ts)
    return bus_to_trajectory

# Slices up a trajectory into each route
def get_cuts(xs,ys,ts):
    cuts = [0]
    time_threshold = 120
    distance_threshold = 1000
    for i in range(len(xs)-1):
        x1,x2 = xs[i],xs[i+1]
        y1,y2 = ys[i],ys[i+1]
        t1,t2 = ts[i],ts[i+1]
        if t2-t1 > time_threshold:
            cuts.append(i+1)
        elif math.sqrt((x2-x1)**2 + (y2-y1)**2) > distance_threshold:
            cuts.append(i+1)
    cuts.append(len(xs))
    return cuts

# Make sure there aren't any weird jumps in speed
def sanitize(times,percentages):
    out = [(percentages[0],times[0])]
    for i in range(len(times)-1):
        p1 = percentages[i]
        p2 = percentages[i+1]
        t1 = times[i]
        t2 = times[i+1]
        if (t2-out[-1][1]) <= 0:
            continue
        speed = total_distance*(p2-out[-1][0])/(t2-out[-1][1])
        if 0 <= speed < 0.7:
            out.append((p2,t2))
    percentages_out = [x[0] for x in out]
    times_out = [x[1] for x in out]
    return percentages_out,times_out

# Just get the location of the stop and their percentage along the route
def get_stops():
    # Represents stops with location
    bus_stop_data, directions = scrapetimetable.ReadRouteConfig(route = 1)
    the_direction = "Inbound" # Or "Outbound"
    tags = []
    for direction in directions:
        if direction[0]["name"] == the_direction:
            tags = set([x["tag"] for x in direction[1:]])
    bus_stop_data = filter(lambda x: x["tag"] in tags,bus_stop_data)
    lats = [float(x["lat"]) for x in bus_stop_data]
    lons = [float(x["lon"]) for x in bus_stop_data]
    xs,ys = gps_to_xy(lats,lons)
    pxs,pys = gps_to_xy(path_lats,path_lons)
    l = map(lambda p: project(p[0],p[1],pxs,pys,total_distance), zip(xs,ys))
    stops = [x[0] for x in l]
    percentages = [x[1] for x in l]
    return percentages, lats, lons

# def get_traffic_estimates(times):
    # out = {}
    # for stop in times:
        # if 10 < stop < n:
            # t = times[stop]
            # out[stop]  = traffic(t,stop)
    # return out

# Computes the arrival time at each stop given the times and z for a bus
def get_arrival_times(times,percentages,stop_percentages):
    current_stop = 0
    out = {}
    i = 0
    delta = 0.005
    for stop,stop_percentage in enumerate(stop_percentages):
        while i < len(percentages)-3 and percentages[i+1] < stop_percentage - delta:
            i += 1
        p1 = percentages[i]
        p2 = percentages[i+1]
        t1 = times[i]
        t2 = times[i+1]
        if p1 - delta < stop_percentage < p1 + delta:
            time = t1
            out[stop]=time
        elif p2 - delta < stop_percentage < p2 + delta:
            time = t2
            out[stop]=time
        elif p1 <= stop_percentage <= p2:
            # Just a little interpolation
            time = t1 + (t2-t1)*(stop_percentage-p1)/(p2-p1)
            out[stop]=time
    return out


def get_parameter_list(l):
    out = str(l[0][0])+","+str(l[0][1])
    for i in range(1,2):
        out += "|" + str(l[i][0]) + "," + str(l[i][1])
    return out

# def traffic(t,i):
    # global count
    # stops = zip(stop_lats,stop_lons)
    # endpoint = "https://maps.googleapis.com/maps/api/distancematrix/json?"
    # origins = "origins=" + str(stops[i][0]) + "," + str(stops[i][1])
    # destinations = "destinations=" + str(stops[i+1][0]) + "," + str(stops[i+1][1])
    # departure_time = "departure_time=" + str(t)
    # key = "key=AIzaSyBWWfg7KDOHa3F3CotzdPINOKyfCIx33lc"
    # parameters = [origins,destinations,key]
    # parameters = "&".join(parameters)
    # url = endpoint + parameters
    # return json.loads(urllib2.urlopen(url).read())['rows'][0]['elements'][0]['duration']['value']

stop_percentages,stop_lats,stop_lons = get_stops()
plot = False
plot_route = False

# Get all the features we want from a file, ready for training
def get_features(file):
    path = get_path()
    total_distance = get_total_distance(path[0],path[1])
    out = []
    bus_to_trajectory = get_trajectory(file)
    for idx,vehicleID in enumerate(bus_to_trajectory):
        # print(float(idx)/len(bus_to_trajectory))
        print idx/len(bus_to_trajectory)*100," percent complete         \r",
        xs,ys,ts = bus_to_trajectory[vehicleID]
        cuts = get_cuts(xs,ys,ts)
        path_x,path_y = get_path()
        for i in range(len(cuts)-1):
            cut_start = cuts[i]
            cut_end = cuts[i+1]
            l = cut_end - cut_start
            if l < 100:
                continue
            xss = xs[cut_start:cut_end]
            yss = ys[cut_start:cut_end]
            tss = ts[cut_start:cut_end]
            mt = min(tss)
            # tss = [x-mt for x in tss]
            projection = [project(x,y,path_x,path_y,total_distance) for (x,y) in zip(xss,yss)]
            percentages = [p[1] for p in projection]
            percentages, tss = sanitize(tss,percentages)
            if len(percentages) < 10:
                continue
            arrival_times = get_arrival_times(tss,percentages,stop_percentages)
            # traffic_estimates = get_traffic_estimates(arrival_times)
            if plot:
                name = "path"
                if plot_route:
                    plt.plot(xss,yss,'bo-',label='Trajectory')
                    plt.axis('equal')
                    plt.xlabel("X position")
                    plt.ylabel("Y position")
                    plt.title("Trajectory along Route 1")
                    first = True
                    t0 = None
                    for i in range(len(tss)):
                        if i>20 and i% 8 == 0:
                            if first:
                                first = False
                                t0 = tss[i]
                            plt.annotate(str(int(tss[i]-t0))+" s", xy=(xss[i],yss[i]))
                else:
                    name = "interpolate"
                    max_t = max(tss)
                    plt.plot(tss,percentages,'bo-',label='Trajectory')
                    plt.ylabel("Percentage progress along route")
                    plt.xlabel("Time")
                    plt.title("1D postion along path with stops")
                    k = 0
                    for p in stop_percentages:
                        if k%5 == 0:
                            plt.plot((0, max_t), (p,p), 'r-')
                        k+=1
                plt.legend()
                plt.savefig("plots/"+name+"_"+str(i)+"_"+str(vehicleID)+".png")
                plt.clf()

            input_vector = {}
            date = datetime.datetime.fromtimestamp(mt).date()
            time = datetime.datetime.fromtimestamp(mt).time()
            schedule_code = scrapetimetable.TimeToScheduleCode(date)
            input_vector["arrival_times"] = arrival_times
            # input_vector["traffic_estimates"] = traffic_estimates
            input_vector["bus_id"] = vehicleID
            input_vector["start_time"] = mt
            input_vector["schedule_code"] = schedule_code
            input_vector["day_of_week"] = date.weekday()
            input_vector["hour"] = time.hour
            input_vector["year"] = date.year
            out.append(input_vector)
    # io.savemat(file[0:-3]+"_out", out, oned_as = 'row')
    with open(file[0:-3]+".json", 'w') as outfile:
        json.dump(out, outfile)
    return out

# print(get_features("/Volumes/Infinity/mbta/h5/2014/mbta_trajectories_2014_15.h5"))

h5filenames = glob('/Volumes/Infinity/mbta/h5/*/*.json')
print(h5filenames)
# for i,file in enumerate(h5filenames):
    # print("Processing file ", i,"/",len(h5filenames))
    # try:
        # get_features(file)
    # except e:
        # print("Error on ", file)


# print([traffic("now",i) for i in 1:28])
